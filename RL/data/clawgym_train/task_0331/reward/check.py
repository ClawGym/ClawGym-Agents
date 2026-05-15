import json
import re
import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def safe_read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_yaml_metric_keys(path: Path):
    # Minimal YAML parser for the provided simple structure
    text = safe_read_text(path)
    if not text:
        return None
    keys = []
    in_metrics = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("metrics:"):
            in_metrics = True
            continue
        if in_metrics:
            if stripped.startswith("- key:"):
                # format: - key: value
                parts = stripped.split(":", 1)
                if len(parts) == 2:
                    keyval = parts[1].strip()
                    # Remove surrounding quotes if present
                    if keyval.startswith('"') and keyval.endswith('"'):
                        keyval = keyval[1:-1]
                    if keyval.startswith("'") and keyval.endswith("'"):
                        keyval = keyval[1:-1]
                    if keyval:
                        keys.append(keyval)
            # Stop parsing metrics if we reach a non-list and non-empty line that is not description
            elif stripped and not stripped.startswith("description:") and not stripped.startswith("- "):
                # possibly the end of metrics
                if keys:
                    break
    if not keys:
        return None
    return keys


def is_iso8601(ts: str) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    # Try parsing with fromisoformat; handle 'Z'
    try:
        t = ts.replace("Z", "+00:00")
        datetime.fromisoformat(t)
        return True
    except Exception:
        return False


def count_words(text: str) -> int:
    tokens = re.findall(r"\b\w[\w'-]*\b", text, flags=re.UNICODE)
    return len(tokens)


def find_section_ranges(md: str, heading_patterns):
    """
    heading_patterns: list of tuples (key, regex pattern string, flags)
    Returns dict: key -> (start_index, end_index) where indices are line indices (inclusive start, exclusive end)
    """
    lines = md.splitlines()
    indices = {}
    # Build normalized header detection: strip leading Markdown '#' and spaces
    for i, line in enumerate(lines):
        norm = line.strip()
        norm = re.sub(r"^#{1,6}\s*", "", norm, flags=re.UNICODE)
        for key, pattern, flags in heading_patterns:
            if key in indices:
                continue
            if re.search(pattern, norm, flags):
                indices[key] = i
    # Determine ranges
    ranges = {}
    for key in indices:
        start = indices[key]
        # find next heading after start
        next_indices = [idx for k2, idx in indices.items() if idx > start]
        end = min(next_indices) if next_indices else len(lines)
        ranges[key] = (start, end)
    return ranges


def section_text(md: str, rng):
    if not rng:
        return ""
    lines = md.splitlines()
    start, end = rng
    # Exclude the heading line itself
    start = min(start + 1, len(lines))
    return "\n".join(lines[start:end]).strip()


def extract_citation_tags(text: str):
    return [int(n) for n in re.findall(r"\[S(\d+)\]", text)]


def validate_domain(domain: str) -> bool:
    # basic check: contains at least one dot, only allowed chars
    if not isinstance(domain, str) or not domain:
        return False
    if "." not in domain:
        return False
    if re.search(r"[^a-zA-Z0-9\.\-\_]", domain):
        return False
    return True


def url_matches_domain(url: str, domain: str) -> bool:
    try:
        netloc = urlparse(url).netloc.lower()
        d = domain.lower()
        return netloc.endswith(d)
    except Exception:
        return False


def validate_process_list(lst):
    if not isinstance(lst, list):
        return False
    if not (1 <= len(lst) <= 5):
        return False
    for item in lst:
        if not isinstance(item, dict):
            return False
        # required keys
        for k in ["pid", "name", "cpu_percent", "memory_percent"]:
            if k not in item:
                return False
        # pid int-like
        if not isinstance(item["pid"], int):
            return False
        # name string
        if not isinstance(item["name"], str):
            return False
        # cpu_percent, memory_percent numeric or None
        for pk in ["cpu_percent", "memory_percent"]:
            val = item.get(pk, None)
            if val is None:
                continue
            if not isinstance(val, (int, float)):
                return False
            if not (val >= 0.0 and val <= 100.0):
                return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "snapshot_json_exists_valid": 0.0,
        "snapshot_has_required_structure": 0.0,
        "snapshot_timestamp_iso8601": 0.0,
        "snapshot_cpu_value_valid": 0.0,
        "snapshot_memory_fields_valid": 0.0,
        "snapshot_disk_fields_valid": 0.0,
        "snapshot_top_processes_cpu_valid": 0.0,
        "snapshot_top_processes_memory_valid": 0.0,
        "sources_json_exists_valid": 0.0,
        "sources_min_two_different_domains": 0.0,
        "sources_schema_fields_valid": 0.0,
        "sources_accessed_date_format_valid": 0.0,
        "sources_domain_url_consistency": 0.0,
        "sources_metrics_covered_valid": 0.0,
        "sources_cover_all_metrics": 0.0,
        "report_exists": 0.0,
        "report_sections_present": 0.0,
        "report_word_limit": 0.0,
        "report_summary_sentence_count_valid": 0.0,
        "report_local_snapshot_links_json_and_bullets": 0.0,
        "report_thresholds_citations_section_covers_all_metrics": 0.0,
        "report_citation_tags_valid": 0.0,
        "report_suggestions_count_2_to_4": 0.0,
        "report_no_external_images_or_remote_content": 0.0,
        "note_rewrite_exists": 0.0,
        "note_rewrite_word_count": 0.0,
        "note_rewrite_supportive_tone_and_experiences": 0.0,
        "note_rewrite_mentions_cleanup_before_upgrades": 0.0,
        "note_rewrite_avoids_judgmental_language": 0.0,
        "message_exists": 0.0,
        "message_word_count": 0.0,
        "message_points_to_report_path": 0.0,
        "message_mentions_experiences": 0.0,
        "message_offers_2_to_3_next_steps": 0.0,
        "message_mentions_key_findings_cpu_mem_disk": 0.0,
    }

    # Paths
    snapshot_path = workspace / "outputs" / "system_snapshot.json"
    sources_path = workspace / "outputs" / "internet_sources.json"
    report_path = workspace / "outputs" / "assessment_report.md"
    note_rewrite_path = workspace / "outputs" / "note_rewrite.txt"
    message_path = workspace / "outputs" / "message_to_alex.txt"
    thresholds_yaml_path = workspace / "input" / "thresholds_spec.yaml"

    metric_keys = parse_yaml_metric_keys(thresholds_yaml_path) or []

    # Validate system snapshot JSON
    snapshot = safe_read_json(snapshot_path)
    if isinstance(snapshot, dict):
        scores["snapshot_json_exists_valid"] = 1.0
        # Required structure keys
        required_keys = ["timestamp", "cpu", "memory", "disk", "top_processes_cpu", "top_processes_memory"]
        has_keys = all(k in snapshot for k in required_keys)
        scores["snapshot_has_required_structure"] = 1.0 if has_keys else 0.0

        # timestamp ISO8601
        ts_ok = False
        ts = snapshot.get("timestamp")
        if isinstance(ts, str) and is_iso8601(ts):
            ts_ok = True
        scores["snapshot_timestamp_iso8601"] = 1.0 if ts_ok else 0.0

        # CPU value
        cpu_ok = False
        cpu_obj = snapshot.get("cpu")
        if isinstance(cpu_obj, dict):
            # Accept "average_utilization_percent" as primary
            cpu_val = cpu_obj.get("average_utilization_percent", None)
            if cpu_val is None:
                # try fallback common names
                for alt in ["avg_utilization_percent", "utilization_percent", "average_percent", "avg_percent"]:
                    cpu_val = cpu_obj.get(alt, None)
                    if cpu_val is not None:
                        break
            if cpu_val is None:
                # allow explicit null
                if "average_utilization_percent" in cpu_obj:
                    cpu_ok = True
            else:
                if isinstance(cpu_val, (int, float)) and 0.0 <= cpu_val <= 100.0:
                    cpu_ok = True
        scores["snapshot_cpu_value_valid"] = 1.0 if cpu_ok else 0.0

        # Memory fields
        mem_ok = False
        mem_obj = snapshot.get("memory")
        if isinstance(mem_obj, dict):
            mem_keys = ["total_mb", "used_mb", "available_mb"]
            if all(k in mem_obj for k in mem_keys):
                mem_ok = True
                for k in mem_keys:
                    v = mem_obj.get(k)
                    if v is None:
                        continue
                    if not isinstance(v, (int, float)):
                        mem_ok = False
                        break
                    if v < 0:
                        mem_ok = False
                        break
        scores["snapshot_memory_fields_valid"] = 1.0 if mem_ok else 0.0

        # Disk fields
        disk_ok = False
        disk_obj = snapshot.get("disk")
        if isinstance(disk_obj, dict):
            disk_keys = ["total_gb", "free_gb"]
            if all(k in disk_obj for k in disk_keys):
                disk_ok = True
                for k in disk_keys:
                    v = disk_obj.get(k)
                    if v is None:
                        continue
                    if not isinstance(v, (int, float)):
                        disk_ok = False
                        break
                    if v < 0:
                        disk_ok = False
                        break
        scores["snapshot_disk_fields_valid"] = 1.0 if disk_ok else 0.0

        # Top processes
        tp_cpu_ok = validate_process_list(snapshot.get("top_processes_cpu", []))
        tp_mem_ok = validate_process_list(snapshot.get("top_processes_memory", []))
        scores["snapshot_top_processes_cpu_valid"] = 1.0 if tp_cpu_ok else 0.0
        scores["snapshot_top_processes_memory_valid"] = 1.0 if tp_mem_ok else 0.0
    else:
        # keep defaults 0.0
        pass

    # Validate internet sources JSON
    sources = safe_read_json(sources_path)
    if isinstance(sources, list) and len(sources) >= 1:
        scores["sources_json_exists_valid"] = 1.0
        # unique domains, at least two
        domains = []
        schema_ok = True
        date_ok_all = True
        domain_url_ok_all = True
        metrics_covered_ok_all = True
        excerpt_ok_all = True

        # Build union of metrics covered
        covered_union = set()

        for item in sources:
            if not isinstance(item, dict):
                schema_ok = False
                continue
            for field in ["source_title", "source_domain", "source_url", "accessed_date", "metrics_covered", "excerpt"]:
                if field not in item:
                    schema_ok = False
            title = item.get("source_title")
            dom = item.get("source_domain")
            url = item.get("source_url")
            adate = item.get("accessed_date")
            met = item.get("metrics_covered")
            exc = item.get("excerpt")

            if not isinstance(title, str) or not title.strip():
                schema_ok = False
            if not isinstance(dom, str) or not validate_domain(dom):
                schema_ok = False
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                schema_ok = False
            else:
                if not url_matches_domain(url, dom):
                    domain_url_ok_all = False
            try:
                datetime.strptime(adate, "%Y-%m-%d")
            except Exception:
                date_ok_all = False
            if not isinstance(met, list) or len(met) == 0 or any(not isinstance(x, str) for x in met):
                metrics_covered_ok_all = False
            else:
                # ensure metrics keys are known from YAML, if available
                if metric_keys:
                    if any(x not in metric_keys for x in met):
                        metrics_covered_ok_all = False
                for x in met:
                    covered_union.add(x)
            if not isinstance(exc, str) or not exc.strip():
                excerpt_ok_all = False
            else:
                # Check excerpt looks like threshold guidance by containing a number or percent
                if re.search(r"\d", exc) is None and "%" not in exc:
                    excerpt_ok_all = False

            if isinstance(dom, str):
                domains.append(dom.lower())

        unique_domains = set(domains)
        scores["sources_min_two_different_domains"] = 1.0 if len(unique_domains) >= 2 else 0.0
        scores["sources_schema_fields_valid"] = 1.0 if schema_ok else 0.0
        scores["sources_accessed_date_format_valid"] = 1.0 if date_ok_all else 0.0
        scores["sources_domain_url_consistency"] = 1.0 if domain_url_ok_all else 0.0
        scores["sources_metrics_covered_valid"] = 1.0 if metrics_covered_ok_all else 0.0
        if metric_keys:
            scores["sources_cover_all_metrics"] = 1.0 if set(metric_keys).issubset(covered_union) else 0.0
        else:
            # If we can't parse YAML metrics, be neutral (0.0) as we cannot verify coverage
            scores["sources_cover_all_metrics"] = 0.0
    else:
        # keep defaults
        pass

    # Validate assessment report
    report_text = safe_read_text(report_path)
    if report_text:
        scores["report_exists"] = 1.0
        # Required sections with headings
        # Accept hyphen-like characters between Low and effort
        hyphen_class = r"[\-\u2010\u2011\u2012\u2013\u2014\u2212\uFE63\uFF0D\s]"
        heading_patterns = [
            ("summary", r"(?i)^summary\s*$", 0),
            ("local_snapshot", r"(?i)^local\s+snapshot\s*$", 0),
            ("thresholds_citations", r"(?i)^thresholds\s*&\s*citations\s*$", 0),
            ("interpretation", r"(?i)^interpretation\s*$", 0),
            ("low_effort_suggestions", rf"(?i)^low{hyphen_class}+effort\s+suggestions\s*$", 0),
        ]
        ranges = find_section_ranges(report_text, heading_patterns)
        sections_present = all(k in ranges for k, _, _ in heading_patterns)
        scores["report_sections_present"] = 1.0 if sections_present else 0.0

        # Word limit < 500
        words = count_words(report_text)
        scores["report_word_limit"] = 1.0 if words <= 500 else 0.0

        # Summary 1-2 sentences
        summ_text = section_text(report_text, ranges.get("summary"))
        # Count sentence terminators
        sent_count = len(re.findall(r"[\.!?](\s|$)", summ_text))
        if sent_count == 0 and summ_text.strip():
            # If no punctuation but content exists, treat as 1 sentence
            sent_count = 1
        scores["report_summary_sentence_count_valid"] = 1.0 if 1 <= sent_count <= 2 else 0.0

        # Local Snapshot: link to outputs/system_snapshot.json and bullet list present
        ls_text = section_text(report_text, ranges.get("local_snapshot"))
        links_json = "outputs/system_snapshot.json" in ls_text
        bullet_lines = [ln for ln in ls_text.splitlines() if re.match(r"^\s*[\-\*\u2022]\s+", ln)]
        ls_ok = links_json and len(bullet_lines) >= 1
        scores["report_local_snapshot_links_json_and_bullets"] = 1.0 if ls_ok else 0.0

        # Thresholds & Citations: cover each metric key present in YAML
        tc_text = section_text(report_text, ranges.get("thresholds_citations"))
        metrics_covered_in_text = True
        if metric_keys:
            for mk in metric_keys:
                if re.search(re.escape(mk), tc_text, flags=re.IGNORECASE) is None:
                    metrics_covered_in_text = False
                    break
        else:
            # If cannot parse metrics, we cannot check coverage
            metrics_covered_in_text = False
        scores["report_thresholds_citations_section_covers_all_metrics"] = 1.0 if metrics_covered_in_text else 0.0

        # Citation tags validity [S1], [S2] within range of sources list length
        tags = extract_citation_tags(report_text)
        tags_ok = False
        sources_list = safe_read_json(sources_path)
        if isinstance(sources_list, list) and len(sources_list) >= 1 and len(tags) >= 1:
            max_index = len(sources_list)
            if all(1 <= t <= max_index for t in tags):
                tags_ok = True
        scores["report_citation_tags_valid"] = 1.0 if tags_ok else 0.0

        # Low-effort Suggestions: 2–4 concrete steps (bullet lines)
        le_text = section_text(report_text, ranges.get("low_effort_suggestions"))
        le_bullets = [ln for ln in le_text.splitlines() if re.match(r"^\s*[\-\*\u2022]\s+", ln)]
        scores["report_suggestions_count_2_to_4"] = 1.0 if 2 <= len(le_bullets) <= 4 else 0.0

        # No external images or remote content in report
        no_images = ("![" not in report_text) and ("<img" not in report_text)
        no_http_links = ("http://" not in report_text and "https://" not in report_text)
        scores["report_no_external_images_or_remote_content"] = 1.0 if (no_images and no_http_links) else 0.0
    else:
        # defaults remain 0
        pass

    # Validate note rewrite
    note_text = safe_read_text(note_rewrite_path)
    if note_text:
        scores["note_rewrite_exists"] = 1.0
        wcount = count_words(note_text)
        scores["note_rewrite_word_count"] = 1.0 if 80 <= wcount <= 120 else 0.0
        # supportive tone and experiences (check for 'experience' substring and positive framing)
        mentions_experiences = re.search(r"\bexperience", note_text, flags=re.IGNORECASE) is not None
        # check not overly judgmental words and overall positive tone markers
        negative_terms = [
            "wasting", "hoarding", "blame", "fault", "irresponsible", "stop", "quit", "crawling",
            "take responsibility", "mess", "lazy", "shame"
        ]
        # Avoid imperative "Stop" as judgmental; we will check separately too
        supportive_markers = ["encourage", "support", "help", "let's", "can", "together", "positive", "enjoy"]
        supportive = any(re.search(rf"\b{re.escape(tok)}\b", note_text, flags=re.IGNORECASE) for tok in supportive_markers)
        scores["note_rewrite_supportive_tone_and_experiences"] = 1.0 if (mentions_experiences and supportive) else 0.0
        # mentions cleanup before upgrades
        cleanup_terms = ["tidy", "clean", "organize", "close", "delete", "remove", "free", "uninstall", "clear"]
        mentions_cleanup = any(re.search(rf"\b{re.escape(tok)}\b", note_text, flags=re.IGNORECASE) for tok in cleanup_terms)
        mentions_upgrades = re.search(r"\bupgrade", note_text, flags=re.IGNORECASE) is not None or re.search(r"\bnew gear\b", note_text, flags=re.IGNORECASE) is not None
        scores["note_rewrite_mentions_cleanup_before_upgrades"] = 1.0 if (mentions_cleanup and mentions_upgrades) else 0.0
        # avoids judgmental language
        has_negative = any(re.search(re.escape(tok), note_text, flags=re.IGNORECASE) for tok in negative_terms)
        scores["note_rewrite_avoids_judgmental_language"] = 1.0 if not has_negative else 0.0
    else:
        # keep defaults
        pass

    # Validate message to Alex
    msg_text = safe_read_text(message_path)
    if msg_text:
        scores["message_exists"] = 1.0
        wc = count_words(msg_text)
        scores["message_word_count"] = 1.0 if 150 <= wc <= 200 else 0.0
        scores["message_points_to_report_path"] = 1.0 if "outputs/assessment_report.md" in msg_text else 0.0
        scores["message_mentions_experiences"] = 1.0 if re.search(r"\bexperience", msg_text, flags=re.IGNORECASE) else 0.0
        # Offer 2–3 specific next steps: detect bullet lines or action keywords
        bullet_lines = [ln for ln in msg_text.splitlines() if re.match(r"^\s*(?:[\-\*\u2022]|\d+\.)\s+", ln)]
        if 2 <= len(bullet_lines) <= 3:
            steps_ok = True
        else:
            action_keywords = ["close", "free", "monitor", "update", "clean", "remove", "uninstall", "organize"]
            present_actions = set()
            for ak in action_keywords:
                if re.search(rf"\b{re.escape(ak)}\b", msg_text, flags=re.IGNORECASE):
                    present_actions.add(ak)
            steps_ok = 2 <= len(present_actions) <= 3
        scores["message_offers_2_to_3_next_steps"] = 1.0 if steps_ok else 0.0
        # Mentions key findings (CPU/memory/disk)
        mentions = 0
        mentions += 1 if re.search(r"\bcpu\b", msg_text, flags=re.IGNORECASE) else 0
        mentions += 1 if re.search(r"\bmemory\b", msg_text, flags=re.IGNORECASE) else 0
        mentions += 1 if re.search(r"\bdisk\b", msg_text, flags=re.IGNORECASE) or re.search(r"\bstorage\b", msg_text, flags=re.IGNORECASE) else 0
        scores["message_mentions_key_findings_cpu_mem_disk"] = 1.0 if mentions >= 2 else 0.0
    else:
        # defaults
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()