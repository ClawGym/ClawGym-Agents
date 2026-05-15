import json
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
import ast
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_monitor_yaml(path: Path) -> Optional[dict]:
    """
    Minimal parser for the specific monitor.yaml structure:
    monitor:
      allowed_domains:
        - domain
      islands:
        - name: NAME
          topics:
            - topic1
            - topic2
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    state = None
    allowed_domains: List[str] = []
    islands: Dict[str, List[str]] = {}
    current_island_name = None
    current_topics: List[str] = []
    i = 0
    try:
        # Basic sanity: file must start with 'monitor:'
        # But we won't enforce position, we'll search for it
        while i < len(lines):
            line = lines[i].strip()
            if line == "monitor:":
                i += 1
                break
            i += 1
        # parse within monitor
        while i < len(lines):
            raw = lines[i]
            stripped = raw.strip()
            if stripped.startswith("allowed_domains:"):
                state = "allowed_domains"
                i += 1
                # collect - items
                while i < len(lines):
                    l = lines[i].strip()
                    if l.startswith("- "):
                        val = l[2:].strip()
                        if val:
                            allowed_domains.append(val)
                        i += 1
                    else:
                        break
                continue
            elif stripped.startswith("islands:"):
                state = "islands"
                i += 1
                while i < len(lines):
                    l = lines[i]
                    s = l.strip()
                    if s.startswith("- name:"):
                        # commit previous island if any
                        if current_island_name is not None:
                            islands[current_island_name] = current_topics
                        # start new island
                        name = s[len("- name:"):].strip()
                        current_island_name = name
                        current_topics = []
                        i += 1
                        # expect topics:
                        while i < len(lines):
                            s2 = lines[i].strip()
                            if s2.startswith("topics:"):
                                i += 1
                                # collect topic items
                                while i < len(lines):
                                    s3 = lines[i].strip()
                                    if s3.startswith("- "):
                                        topic = s3[2:].strip()
                                        if topic:
                                            current_topics.append(topic)
                                        i += 1
                                    else:
                                        break
                                break
                            elif s2.startswith("- name:") or s2 == "":
                                break
                            else:
                                i += 1
                        continue
                    else:
                        i += 1
                # commit last island
                if current_island_name is not None and current_island_name not in islands:
                    islands[current_island_name] = current_topics
                continue
            else:
                i += 1
        return {"allowed_domains": allowed_domains, "islands": islands}
    except Exception:
        return None


def _parse_query_map_py(path: Path) -> Optional[Dict[str, List[str]]]:
    """
    Extract KEYWORDS mapping via AST literal evaluation.
    """
    text = _read_text(path)
    if text is None:
        return None
    try:
        tree = ast.parse(text, filename=str(path))
        mapping = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "KEYWORDS":
                        mapping = ast.literal_eval(node.value)
                        break
            if mapping is not None:
                break
        if mapping is None or not isinstance(mapping, dict):
            return None
        # Normalize string lists
        cleaned: Dict[str, List[str]] = {}
        for k, v in mapping.items():
            if isinstance(k, str) and isinstance(v, (list, tuple)):
                cleaned[k] = [str(x) for x in v]
        return cleaned
    except Exception:
        return None


def _load_csv_dicts(path: Path, required_columns: List[str]) -> Tuple[Optional[List[Dict[str, str]]], bool]:
    try:
        with path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            fieldnames = [fn.strip() for fn in rdr.fieldnames] if rdr.fieldnames else []
            if fieldnames != required_columns:
                # strictly require exact columns and order
                return None, False
            rows = []
            for row in rdr:
                # keep exactly as strings
                rows.append({k: row.get(k, "").strip() for k in required_columns})
            return rows, True
    except Exception:
        return None, False


def _unique_url_counts(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str], int]:
    mapping: Dict[Tuple[str, str], set] = {}
    for r in rows:
        key = (r.get("island", ""), r.get("topic", ""))
        url = r.get("url", "")
        if key not in mapping:
            mapping[key] = set()
        if url:
            mapping[key].add(url)
    return {k: len(v) for k, v in mapping.items()}


def _extract_section(text: str, heading: str, all_headings: List[str]) -> str:
    """
    Extract content under a heading line matching exactly 'heading'
    until the next heading (from all_headings) or end of file.
    """
    lines = text.splitlines()
    start_idx = None
    for idx, ln in enumerate(lines):
        if ln.strip() == heading:
            start_idx = idx + 1
            break
    if start_idx is None:
        return ""
    # Find next heading
    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        if lines[idx].strip() in all_headings:
            end_idx = idx
            break
    content_lines = lines[start_idx:end_idx]
    return "\n".join(content_lines).strip()


def _count_sentences(text: str) -> int:
    # Count end-of-sentence punctuation occurrences
    # Consider cases like "Mr." -> heuristic; we'll keep simple.
    matches = re.findall(r"[.!?](\s|$)", text)
    return len(matches)


def _parse_markdown_table(text: str) -> Tuple[List[str], List[List[str]]]:
    """
    Parse a simple GitHub-flavored markdown table.
    Returns (headers, rows) where rows are lists of cell strings.
    """
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    header = []
    rows: List[List[str]] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if "|" in ln:
            # candidate header
            header_cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            # next line should be separator with dashes and pipes
            if i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+[:\- ]*\s*(\|\s*:?-+[:\- ]*\s*)+\|?\s*$", lines[i + 1]):
                header = header_cells
                i += 2
                break
        i += 1
    if not header:
        return [], []
    # parse rows until a blank line or non-table line
    while i < len(lines):
        ln = lines[i]
        if "|" not in ln:
            break
        row_cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        # pad or trim to header length
        if len(row_cells) < len(header):
            row_cells += [""] * (len(header) - len(row_cells))
        elif len(row_cells) > len(header):
            row_cells = row_cells[:len(header)]
        rows.append(row_cells)
        i += 1
    return header, rows


def _host_matches_domain(host: Optional[str], domain: str) -> bool:
    if not host:
        return False
    host = host.lower()
    domain = domain.lower()
    return host == domain or host.endswith("." + domain)


def _compute_discrepancies(yaml_islands: Dict[str, List[str]], script_map: Optional[Dict[str, List[str]]]) -> Dict[str, Dict[str, List[str]]]:
    """
    Return discrepancies per island:
    {
      island: {
        "only_in_yaml": [...],
        "only_in_script": [...],
      }
    }
    Only include islands with any discrepancy.
    """
    discrepancies: Dict[str, Dict[str, List[str]]] = {}
    script_map = script_map or {}
    all_islands = set(yaml_islands.keys()) | set(script_map.keys())
    for isl in sorted(all_islands):
        y_topics = set(yaml_islands.get(isl, []))
        s_topics = set(script_map.get(isl, []))
        only_yaml = sorted(list(y_topics - s_topics))
        only_script = sorted(list(s_topics - y_topics))
        if only_yaml or only_script:
            discrepancies[isl] = {"only_in_yaml": only_yaml, "only_in_script": only_script}
    return discrepancies


def _parse_trend_deltas_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], bool]:
    required = ["island", "topic", "baseline_count", "current_count", "delta", "status"]
    return _load_csv_dicts(path, required)


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "raw_mentions_structure": 0.0,
        "raw_mentions_allowed_domains_and_titles": 0.0,
        "raw_mentions_per_pair_max_two_urls": 0.0,
        "search_log_coverage_and_counts": 0.0,
        "current_counts_structure": 0.0,
        "current_counts_coverage": 0.0,
        "current_counts_matches_raw": 0.0,
        "trend_deltas_structure": 0.0,
        "trend_deltas_consistency": 0.0,
        "trend_update_sections": 0.0,
        "executive_summary_sentence_count": 0.0,
        "highlights_cover_top_changes": 0.0,
        "island_notes_per_island": 0.0,
        "configuration_check_discrepancies_listed": 0.0,
        "meeting_notes_agenda": 0.0,
        "meeting_notes_table_structure": 0.0,
        "meeting_notes_rows_coverage_and_values": 0.0,
    }

    # Load monitor.yaml
    monitor_path = workspace / "input" / "config" / "monitor.yaml"
    monitor = _parse_monitor_yaml(monitor_path)
    if not monitor:
        # Without monitor, most checks cannot proceed; return zeros with keys present
        return scores
    allowed_domains = monitor.get("allowed_domains", [])
    yaml_islands: Dict[str, List[str]] = monitor.get("islands", {})
    all_pairs = [(isl, topic) for isl, topics in yaml_islands.items() for topic in topics]

    # Load query_map to compute discrepancies
    query_map_path = workspace / "input" / "scripts" / "query_map.py"
    script_map = _parse_query_map_py(query_map_path)
    discrepancies = _compute_discrepancies(yaml_islands, script_map)

    # Check outputs/raw/current_mentions.csv
    raw_mentions_path = workspace / "outputs" / "raw" / "current_mentions.csv"
    raw_required_cols = ["island", "topic", "url", "page_title", "domain"]
    raw_rows, raw_ok = _load_csv_dicts(raw_mentions_path, raw_required_cols)
    if raw_ok and raw_rows is not None:
        scores["raw_mentions_structure"] = 1.0
        # Allowed domains and titles
        passed = True
        for r in raw_rows:
            dom = r.get("domain", "")
            url = r.get("url", "")
            title = r.get("page_title", "")
            if dom not in allowed_domains:
                passed = False
                break
            parsed = urlparse(url)
            if not _host_matches_domain(parsed.hostname, dom):
                passed = False
                break
            # Require non-empty title with at least one letter
            if not isinstance(title, str) or len(title.strip()) == 0 or not re.search(r"[A-Za-z]", title):
                passed = False
                break
        scores["raw_mentions_allowed_domains_and_titles"] = 1.0 if passed else 0.0

        # per pair max two unique URLs
        counts_by_pair = _unique_url_counts(raw_rows)
        max_two_total = 0
        for pair in all_pairs:
            cnt = counts_by_pair.get(pair, 0)
            if cnt <= 2:
                max_two_total += 1
        if len(all_pairs) > 0:
            scores["raw_mentions_per_pair_max_two_urls"] = max_two_total / len(all_pairs)
        else:
            # no pairs -> vacuous pass
            scores["raw_mentions_per_pair_max_two_urls"] = 1.0
    else:
        # Missing or malformed structure
        scores["raw_mentions_structure"] = 0.0
        scores["raw_mentions_allowed_domains_and_titles"] = 0.0
        scores["raw_mentions_per_pair_max_two_urls"] = 0.0
        raw_rows = []

    # Search log check
    search_log_path = workspace / "outputs" / "raw" / "search_log.md"
    search_text = _read_text(search_log_path)
    if search_text is not None:
        lines = [ln for ln in search_text.splitlines() if ln.strip()]
        # Build unique counts from raw
        unique_counts = _unique_url_counts(raw_rows) if raw_rows is not None else {}
        pairs_ok = 0
        for (isl, topic) in all_pairs:
            # find a line that includes the island and topic and 'site:' and one of allowed domains
            matches = []
            for ln in lines:
                ln_low = ln.lower()
                if isl.lower() in ln_low and topic.lower() in ln_low and "site:" in ln_low:
                    # must include any allowed domain
                    if any(ad.lower() in ln_low for ad in allowed_domains):
                        matches.append(ln)
            if len(matches) != 1:
                continue
            line = matches[0]
            # Extract a recorded count as the last integer in the line
            nums = re.findall(r"\b(\d+)\b", line)
            if not nums:
                continue
            recorded = int(nums[-1])
            expected = unique_counts.get((isl, topic), 0)
            if recorded == expected:
                pairs_ok += 1
        scores["search_log_coverage_and_counts"] = (pairs_ok / len(all_pairs)) if all_pairs else 1.0
    else:
        scores["search_log_coverage_and_counts"] = 0.0

    # Current counts check
    counts_path = workspace / "outputs" / "analysis" / "current_counts.csv"
    counts_required = ["island", "topic", "current_count"]
    counts_rows, counts_ok = _load_csv_dicts(counts_path, counts_required)
    if counts_ok and counts_rows is not None:
        scores["current_counts_structure"] = 1.0
        # Coverage: exactly one row per pair defined in YAML
        seen_pairs = {(r["island"], r["topic"]) for r in counts_rows}
        expected_pairs = set(all_pairs)
        coverage_ok = seen_pairs == expected_pairs
        scores["current_counts_coverage"] = 1.0 if coverage_ok else 0.0
        # Match raw unique URL counts
        unique_counts = _unique_url_counts(raw_rows) if raw_rows is not None else {}
        correct = 0
        total = 0
        for isl, topic in all_pairs:
            # find row
            row = next((r for r in counts_rows if r["island"] == isl and r["topic"] == topic), None)
            if row is None:
                total += 1
                continue
            cc = _safe_int(row.get("current_count", ""))
            if cc is None:
                total += 1
                continue
            exp = unique_counts.get((isl, topic), 0)
            if cc == exp:
                correct += 1
            total += 1
        scores["current_counts_matches_raw"] = (correct / total) if total else 1.0
    else:
        scores["current_counts_structure"] = 0.0
        scores["current_counts_coverage"] = 0.0
        scores["current_counts_matches_raw"] = 0.0
        counts_rows = []

    # Trend deltas checks
    trend_path = workspace / "outputs" / "analysis" / "trend_deltas.csv"
    trend_rows, trend_ok = _parse_trend_deltas_csv(trend_path)
    if trend_ok and trend_rows is not None:
        scores["trend_deltas_structure"] = 1.0
        # Load baseline
        baseline_path = workspace / "input" / "baseline" / "mentions_baseline.csv"
        baseline_rows, baseline_ok = _load_csv_dicts(baseline_path, ["island", "topic", "baseline_count"])
        baseline_map: Dict[Tuple[str, str], int] = {}
        if baseline_ok and baseline_rows is not None:
            for r in baseline_rows:
                k = (r["island"], r["topic"])
                v = _safe_int(r.get("baseline_count", ""))
                if v is None:
                    # malformed baseline: fail consistency entirely
                    baseline_map = {}
                    break
                baseline_map[k] = v
        # Current counts map
        counts_map: Dict[Tuple[str, str], int] = {}
        for r in (counts_rows or []):
            k = (r["island"], r["topic"])
            v = _safe_int(r.get("current_count", ""))
            if v is not None:
                counts_map[k] = v

        # Validate trend rows per pair
        correct = 0
        total = 0
        trend_map: Dict[Tuple[str, str], Dict[str, str]] = {}
        for r in trend_rows:
            k = (r["island"], r["topic"])
            trend_map[k] = r

        for isl, topic in all_pairs:
            k = (isl, topic)
            tr = trend_map.get(k)
            if tr is None:
                total += 1
                continue
            b = _safe_int(tr.get("baseline_count", ""))
            c = _safe_int(tr.get("current_count", ""))
            d = _safe_int(tr.get("delta", ""))
            s = tr.get("status", "")
            # must match baseline and counts
            bm = baseline_map.get(k)
            cm = counts_map.get(k)
            if bm is None or cm is None or b is None or c is None or d is None:
                total += 1
                continue
            if b != bm or c != cm:
                total += 1
                continue
            if d != (c - b):
                total += 1
                continue
            expected_status = "no_change" if d == 0 else ("up" if d > 0 else "down")
            if s != expected_status:
                total += 1
                continue
            correct += 1
            total += 1
        scores["trend_deltas_consistency"] = (correct / total) if total else 1.0
    else:
        scores["trend_deltas_structure"] = 0.0
        scores["trend_deltas_consistency"] = 0.0
        trend_rows = []

    # Report: trend_update.md
    trend_report_path = workspace / "outputs" / "reports" / "trend_update.md"
    report_text = _read_text(trend_report_path)
    headings = [
        "Executive Summary:",
        "Highlights:",
        "Island-by-Island Notes:",
        "Configuration Check:",
    ]
    if report_text is not None:
        # Sections presence
        present = [1 if heading in report_text else 0 for heading in headings]
        scores["trend_update_sections"] = sum(present) / len(headings)
        # Executive Summary sentences count
        exec_text = _extract_section(report_text, "Executive Summary:", headings)
        sent_count = _count_sentences(exec_text)
        scores["executive_summary_sentence_count"] = 1.0 if 3 <= sent_count <= 5 else 0.0

        # Highlights coverage of top changes
        # Build deltas from trend_rows
        deltas: List[Tuple[str, str, int]] = []
        for r in (trend_rows or []):
            isl = r.get("island", "")
            topic = r.get("topic", "")
            d = _safe_int(r.get("delta", ""))
            if isl and topic and d is not None:
                deltas.append((isl, topic, d))
        # Determine top increases and decreases
        pos = [(i, t, d) for (i, t, d) in deltas if d > 0]
        neg = [(i, t, d) for (i, t, d) in deltas if d < 0]
        pos_sorted = sorted(pos, key=lambda x: (-x[2], x[0], x[1]))[:3]
        neg_sorted = sorted(neg, key=lambda x: (x[2], x[0], x[1]))[:3]  # d is negative, ascending = most negative
        highlights_text = _extract_section(report_text, "Highlights:", headings)
        high_ok = 0
        high_total = 0
        for isl, topic, _ in pos_sorted:
            high_total += 1
            if isl in highlights_text and topic in highlights_text:
                high_ok += 1
        for isl, topic, _ in neg_sorted:
            high_total += 1
            if isl in highlights_text and topic in highlights_text:
                high_ok += 1
        scores["highlights_cover_top_changes"] = (high_ok / high_total) if high_total else 1.0

        # Island-by-Island Notes: one short paragraph per island mentioning statuses
        notes_text = _extract_section(report_text, "Island-by-Island Notes:", headings)
        # Split paragraphs by blank lines
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", notes_text) if p.strip()]
        island_ok = 0
        for isl in yaml_islands.keys():
            matched = False
            for p in paragraphs:
                if isl in p:
                    # must contain at least one status keyword
                    if re.search(r"\b(up|down|no[_ ]?change)\b", p, re.IGNORECASE):
                        matched = True
                        break
            if matched:
                island_ok += 1
        scores["island_notes_per_island"] = (island_ok / len(yaml_islands)) if yaml_islands else 1.0

        # Configuration Check: discrepancies listed
        conf_text = _extract_section(report_text, "Configuration Check:", headings)
        # We require that for each discrepancy topic, the island and differing topic string appear
        # If an island has both 'only_in_yaml' and 'only_in_script', we expect mention of both differing topics.
        disc_total = 0
        disc_ok = 0
        for isl, diff in discrepancies.items():
            for t in diff.get("only_in_yaml", []):
                disc_total += 1
                if isl in conf_text and t in conf_text:
                    disc_ok += 1
            for t in diff.get("only_in_script", []):
                disc_total += 1
                if isl in conf_text and t in conf_text:
                    disc_ok += 1
        scores["configuration_check_discrepancies_listed"] = (disc_ok / disc_total) if disc_total else 1.0
    else:
        scores["trend_update_sections"] = 0.0
        scores["executive_summary_sentence_count"] = 0.0
        scores["highlights_cover_top_changes"] = 0.0
        scores["island_notes_per_island"] = 0.0
        scores["configuration_check_discrepancies_listed"] = 0.0

    # Meeting notes
    meeting_path = workspace / "outputs" / "reports" / "meeting_notes.md"
    meeting_text = _read_text(meeting_path)
    if meeting_text is not None:
        # Agenda presence
        # Require that it includes mention of purpose, inputs reviewed, outputs produced
        has_purpose = re.search(r"purpose", meeting_text, re.IGNORECASE) is not None
        has_inputs = re.search(r"inputs reviewed", meeting_text, re.IGNORECASE) is not None or re.search(r"inputs", meeting_text, re.IGNORECASE) is not None
        has_outputs = re.search(r"outputs produced", meeting_text, re.IGNORECASE) is not None or re.search(r"outputs", meeting_text, re.IGNORECASE) is not None
        agenda_score = (int(has_purpose) + int(has_inputs) + int(has_outputs)) / 3.0
        scores["meeting_notes_agenda"] = agenda_score

        # Table structure and rows
        header, rows = _parse_markdown_table(meeting_text)
        expected_header = ["island", "topic", "status", "suggested_action", "owner", "due_in_days"]
        if [h.lower() for h in header] == expected_header:
            scores["meeting_notes_table_structure"] = 1.0
            # Validate rows coverage and values
            # Build map from trend_deltas for status
            trend_map = {}
            if trend_rows:
                for r in trend_rows:
                    k = (r["island"], r["topic"])
                    trend_map[k] = r.get("status", "")
            # Validate each expected pair present exactly once
            row_map: Dict[Tuple[str, str], Dict[str, str]] = {}
            for r in rows:
                rd = dict(zip(expected_header, r))
                key = (rd.get("island", ""), rd.get("topic", ""))
                row_map[key] = rd
            total_pairs = len(all_pairs)
            correct = 0
            for isl, topic in all_pairs:
                key = (isl, topic)
                rd = row_map.get(key)
                if rd is None:
                    continue
                status = rd.get("status", "")
                # Check status matches trend_deltas.csv
                expected_status = trend_map.get(key, "")
                if not expected_status or status != expected_status:
                    continue
                # suggested_action depends on status
                expected_action = {"up": "amplify talking points and visuals",
                                   "down": "refresh content or seek partner posts",
                                   "no_change": "monitor"}.get(status, None)
                if rd.get("suggested_action", "") != (expected_action or ""):
                    continue
                if rd.get("owner", "") != "Guide Team":
                    continue
                if rd.get("due_in_days", "") != "14":
                    continue
                correct += 1
            coverage_score = (correct / total_pairs) if total_pairs else 1.0
            scores["meeting_notes_rows_coverage_and_values"] = coverage_score
        else:
            scores["meeting_notes_table_structure"] = 0.0
            scores["meeting_notes_rows_coverage_and_values"] = 0.0
    else:
        scores["meeting_notes_agenda"] = 0.0
        scores["meeting_notes_table_structure"] = 0.0
        scores["meeting_notes_rows_coverage_and_values"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()