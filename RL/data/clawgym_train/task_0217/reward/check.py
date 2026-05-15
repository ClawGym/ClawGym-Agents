import csv
import json
import re
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from collections import Counter, defaultdict


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _parse_topics_yaml(yaml_path: Path):
    """
    Minimal parser for the specific topics.yaml structure provided.
    Returns a list of dicts: [{"name": str, "keywords": [str, ...]}, ...]
    """
    text = _safe_read_text(yaml_path)
    if not text:
        return []
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    topics = []
    i = 0
    # find "topics:" line
    while i < len(lines) and not lines[i].strip().startswith("topics:"):
        i += 1
    if i >= len(lines):
        return []
    i += 1
    current = None
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("- name:"):
            # close previous
            if current:
                topics.append(current)
            name = stripped[len("- name:"):].strip().strip('"').strip("'")
            current = {"name": name, "keywords": []}
        elif stripped.startswith("keywords:"):
            # Next lines are indented keyword items starting with "-"
            i += 1
            while i < len(lines):
                l2 = lines[i]
                s2 = l2.strip()
                if s2.startswith("- "):
                    kw = s2[2:].strip().strip('"').strip("'")
                    if current is not None and kw:
                        current["keywords"].append(kw)
                    i += 1
                else:
                    break
            continue  # already advanced i in inner loop
        i += 1
    if current:
        topics.append(current)
    return topics


def _read_exclusions(path: Path):
    text = _safe_read_text(path)
    if not text:
        return []
    return [ln.strip().lower() for ln in text.splitlines() if ln.strip()]


def _slugify_topic(name: str) -> str:
    return name.lower().replace(" ", "-")


def _sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc
        # strip credentials and port if any
        if "@" in netloc:
            netloc = netloc.split("@", 1)[1]
        if ":" in netloc:
            netloc = netloc.split(":", 1)[0]
        return netloc.lower()
    except Exception:
        return ""


def _tld_type(domain: str) -> str:
    dom = domain.lower()
    # Extract last label for naive TLD type classification
    if "." in dom:
        tld = dom.rsplit(".", 1)[-1]
    else:
        tld = dom
    if tld == "org":
        return "org"
    if tld == "edu":
        return "edu"
    if tld == "gov":
        return "gov"
    if tld == "com":
        return "com"
    return "other"


def _is_iso8601(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    # Handle 'Z' timezone
    ss = s
    if ss.endswith("Z"):
        ss = ss[:-1] + "+00:00"
    try:
        datetime.fromisoformat(ss)
        return True
    except Exception:
        return False


def _word_count(text: str) -> int:
    if not text or not isinstance(text, str):
        return 0
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _load_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def _load_json(path: Path):
    try:
        return json.loads(_safe_read_text(path))
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "queries_log_present": 0.0,
        "queries_log_topics_covered": 0.0,
        "queries_log_keywords_used": 0.0,
        "resources_csv_present": 0.0,
        "resources_csv_header_valid": 0.0,
        "resources_total_count_minimum": 0.0,
        "per_row_id_matches_url_sha1": 0.0,
        "per_row_raw_html_exists": 0.0,
        "per_row_topic_valid": 0.0,
        "per_row_source_domain_matches_url": 0.0,
        "per_row_tld_type_correct": 0.0,
        "per_row_retrieved_at_iso8601": 0.0,
        "per_row_title_present": 0.0,
        "per_row_summary_word_count_range": 0.0,
        "per_row_publication_year_valid": 0.0,
        "urls_unique": 0.0,
        "coverage_min_two_per_topic": 0.0,
        "authoritative_domain_fraction": 0.0,
        "exclusions_respected_fraction": 0.0,
        "stats_json_present": 0.0,
        "stats_total_resources_matches_csv": 0.0,
        "stats_by_topic_correct": 0.0,
        "stats_by_tld_type_correct": 0.0,
        "stats_unique_domains_count_correct": 0.0,
        "stats_top_domains_valid": 0.0,
        "stats_summary_word_count_mean_correct": 0.0,
        "stats_missing_publication_year_count_correct": 0.0,
    }

    # Inputs
    topics_yaml = workspace / "input" / "topics.yaml"
    exclusions_txt = workspace / "input" / "exclusions.txt"
    topics = _parse_topics_yaml(topics_yaml)
    exclusions = _read_exclusions(exclusions_txt)

    # Script check
    script_path = workspace / "scripts" / "collect_resources"
    if script_path.exists() and script_path.is_file():
        # Check executable bit or .py/.sh extension
        is_exec = False
        try:
            is_exec = script_path.stat().st_mode & 0o111 != 0
        except Exception:
            is_exec = False
        ext_ok = script_path.suffix in (".py", ".sh") or script_path.name.endswith(".py") or script_path.name.endswith(".sh")
        if is_exec or ext_ok:
            scores["script_exists"] = 1.0

    # Queries log checks
    queries_path = workspace / "output" / "queries_used.txt"
    queries_text = _safe_read_text(queries_path)
    if queries_text:
        scores["queries_log_present"] = 1.0
        query_lines = [ln.strip() for ln in queries_text.splitlines() if ln.strip()]
        # For topics coverage: at least one query per topic that includes the topic name
        if topics:
            covered = 0
            keywords_used = 0
            for t in topics:
                name = t.get("name", "")
                kws = [k.lower() for k in t.get("keywords", [])]
                name_l = name.lower()
                found_name = False
                found_kw = False
                for q in query_lines:
                    ql = q.lower()
                    if name_l in ql:
                        found_name = True
                        # check if any keyword present
                        if any(kw in ql for kw in kws):
                            found_kw = True
                if found_name:
                    covered += 1
                if found_kw:
                    keywords_used += 1
            if len(topics) > 0:
                scores["queries_log_topics_covered"] = covered / len(topics)
                scores["queries_log_keywords_used"] = keywords_used / len(topics)
    else:
        # Missing queries file; keep related scores at 0.0
        pass

    # Resources CSV checks
    resources_csv_path = workspace / "output" / "resources.csv"
    rows = _load_csv(resources_csv_path)
    header_expected = [
        "id",
        "url",
        "topic",
        "title",
        "source_domain",
        "tld_type",
        "publication_year",
        "retrieved_at",
        "summary",
    ]
    if rows is not None and len(rows) >= 1:
        scores["resources_csv_present"] = 1.0
        header = rows[0]
        if header == header_expected:
            scores["resources_csv_header_valid"] = 1.0
        data_rows = rows[1:]
        n = len(data_rows)
        # Minimum total
        if n > 0:
            scores["resources_total_count_minimum"] = min(n / 8.0, 1.0)
        # Prepare per-row checks
        id_ok = 0
        raw_ok = 0
        topic_ok = 0
        domain_ok = 0
        tld_ok = 0
        time_ok = 0
        title_ok = 0
        summary_ok = 0
        pubyear_ok = 0
        authoritative_ok = 0
        exclusion_ok = 0

        urls = []
        topic_counts = Counter()
        tld_counts = Counter()
        domains_list = []

        # Build set for topics names
        topic_names = set(t.get("name", "") for t in topics) if topics else set()

        for row in data_rows:
            if len(row) != len(header_expected):
                # Malformed row counts as failures for all per-row checks
                continue
            rid, url, topic, title, source_domain, tld_type, publication_year, retrieved_at, summary = row
            urls.append(url)
            domains_list.append(source_domain)
            tld_counts[tld_type] += 1
            topic_counts[topic] += 1

            # id SHA-1 of URL
            try:
                sha = _sha1_hex(url)
                if rid == sha and re.fullmatch(r"[0-9a-f]{40}", rid or ""):
                    id_ok += 1
            except Exception:
                pass

            # raw html exists at output/raw/<topic-slug>/<id>.html
            slug = _slugify_topic(topic)
            raw_path = workspace / "output" / "raw" / slug / f"{rid}.html"
            if raw_path.exists() and raw_path.is_file():
                raw_ok += 1
                raw_text = _safe_read_text(raw_path)
            else:
                raw_text = ""

            # topic is one of topic names from input/topics.yaml
            if topic in topic_names and topic != "":
                topic_ok += 1

            # source_domain matches URL netloc (lowercased, no port)
            domain = _domain_from_url(url)
            if domain and (domain == source_domain.lower()):
                domain_ok += 1

            # tld_type correctness based on source_domain
            expected_tld = _tld_type(source_domain)
            if tld_type == expected_tld:
                tld_ok += 1

            # retrieved_at ISO-8601
            if _is_iso8601(retrieved_at):
                time_ok += 1

            # title non-empty
            if isinstance(title, str) and title.strip():
                title_ok += 1

            # summary word count between 80 and 200 inclusive
            wc = _word_count(summary)
            if 80 <= wc <= 200:
                summary_ok += 1

            # publication_year empty or 4-digit reasonable year
            pub_valid = False
            if publication_year is None or publication_year == "":
                pub_valid = True
            else:
                if re.fullmatch(r"\d{4}", publication_year):
                    try:
                        yr = int(publication_year)
                        current_year = datetime.now().year
                        if 1900 <= yr <= current_year + 1:
                            pub_valid = True
                    except Exception:
                        pub_valid = False
            if pub_valid:
                pubyear_ok += 1

            # Authoritative domain (.org, .edu, .gov)
            if tld_type in {"org", "edu", "gov"}:
                authoritative_ok += 1

            # Exclusions respected: URL and raw text must not contain any term (case-insensitive)
            url_l = (url or "").lower()
            raw_l = (raw_text or "").lower()
            has_excl = False
            for term in exclusions:
                if term and (term in url_l or (raw_text != "" and term in raw_l)):
                    has_excl = True
                    break
            if not has_excl and raw_text != "":
                exclusion_ok += 1

        # Set per-row checks scores
        if n > 0:
            scores["per_row_id_matches_url_sha1"] = id_ok / n
            scores["per_row_raw_html_exists"] = raw_ok / n
            scores["per_row_topic_valid"] = topic_ok / n
            scores["per_row_source_domain_matches_url"] = domain_ok / n
            scores["per_row_tld_type_correct"] = tld_ok / n
            scores["per_row_retrieved_at_iso8601"] = time_ok / n
            scores["per_row_title_present"] = title_ok / n
            scores["per_row_summary_word_count_range"] = summary_ok / n
            scores["per_row_publication_year_valid"] = pubyear_ok / n
            scores["authoritative_domain_fraction"] = authoritative_ok / n
            scores["exclusions_respected_fraction"] = exclusion_ok / n

        # URLs unique across whole set
        if n > 0:
            unique_url_count = len(set(urls))
            scores["urls_unique"] = 1.0 if unique_url_count == n else 0.0

        # Coverage: at least 2 per topic
        if topics:
            topic_min2 = 0
            for t in topics:
                cnt = topic_counts.get(t["name"], 0)
                if cnt >= 2:
                    topic_min2 += 1
            scores["coverage_min_two_per_topic"] = topic_min2 / len(topics)

    # Stats checks
    stats_path = workspace / "output" / "stats.json"
    stats = _load_json(stats_path)
    if isinstance(stats, dict):
        scores["stats_json_present"] = 1.0

    # If both CSV and stats exist, validate consistency
    if rows is not None and len(rows) >= 1 and isinstance(stats, dict):
        data_rows = rows[1:]
        n = len(data_rows)
        # Build expected aggregates
        # Summary word counts
        summaries_wc = []
        by_topic_exp = Counter()
        by_tld_exp = Counter()
        domains_exp = []
        missing_pub_year_exp = 0

        for row in data_rows:
            if len(row) != 9:
                # Malformed row; treat as missing for stats checks
                continue
            rid, url, topic, title, source_domain, tld_type, publication_year, retrieved_at, summary = row
            by_topic_exp[topic] += 1
            by_tld_exp[tld_type] += 1
            domains_exp.append(source_domain)
            wc = _word_count(summary)
            summaries_wc.append(wc)
            if publication_year is None or publication_year == "":
                missing_pub_year_exp += 1

        # total_resources
        try:
            total_resources_stat = int(stats.get("total_resources"))
        except Exception:
            total_resources_stat = None
        if total_resources_stat == len(data_rows):
            scores["stats_total_resources_matches_csv"] = 1.0

        # by_topic
        by_topic_stat = stats.get("by_topic")
        if isinstance(by_topic_stat, dict):
            # Ensure counts match for topics present in CSV
            match = True
            # Convert keys to string
            for tname, cnt in by_topic_exp.items():
                if by_topic_stat.get(tname) != cnt:
                    match = False
                    break
            # Also check that sum equals total_resources
            sum_stat = 0
            try:
                sum_stat = sum(int(v) for v in by_topic_stat.values())
            except Exception:
                match = False
            if match and total_resources_stat == sum_stat:
                scores["stats_by_topic_correct"] = 1.0

        # by_tld_type
        by_tld_stat = stats.get("by_tld_type")
        if isinstance(by_tld_stat, dict):
            match = True
            for tld, cnt in by_tld_exp.items():
                if by_tld_stat.get(tld) != cnt:
                    match = False
                    break
            sum_stat = 0
            try:
                sum_stat = sum(int(v) for v in by_tld_stat.values())
            except Exception:
                match = False
            if match and total_resources_stat == sum_stat:
                scores["stats_by_tld_type_correct"] = 1.0

        # unique_domains_count
        unique_domains_count_exp = len(set(domains_exp))
        try:
            unique_domains_count_stat = int(stats.get("unique_domains_count"))
        except Exception:
            unique_domains_count_stat = None
        if unique_domains_count_stat == unique_domains_count_exp:
            scores["stats_unique_domains_count_correct"] = 1.0

        # top_domains: array of up to 3 {domain, count}, sorted by count desc
        top_domains_stat = stats.get("top_domains")
        if isinstance(top_domains_stat, list):
            # Build domain counts
            dc = Counter(domains_exp)
            # Validate counts non-increasing and values accurate
            valid = True
            last_count = None
            for item in top_domains_stat:
                if not isinstance(item, dict):
                    valid = False
                    break
                dom = item.get("domain")
                cnt = item.get("count")
                if not isinstance(dom, str) or not isinstance(cnt, int):
                    valid = False
                    break
                if dc.get(dom, None) != cnt:
                    valid = False
                    break
                if last_count is not None and cnt > last_count:
                    valid = False
                    break
                last_count = cnt
            # Ensure length <= 3 and domains are among highest counts
            if valid:
                valid = len(top_domains_stat) <= 3
            if valid and len(dc) > 0:
                # compute threshold count for top 3
                counts_sorted = sorted(dc.values(), reverse=True)
                threshold = counts_sorted[min(2, len(counts_sorted) - 1)]
                for item in top_domains_stat:
                    if item.get("count", 0) < threshold and len(counts_sorted) >= 3:
                        valid = False
                        break
            if valid:
                scores["stats_top_domains_valid"] = 1.0

        # summary_word_count_mean rounded to one decimal
        try:
            mean_stat = stats.get("summary_word_count_mean")
            # Accept number (int or float)
            if isinstance(mean_stat, (int, float)):
                if summaries_wc:
                    mean_exp = sum(summaries_wc) / len(summaries_wc)
                else:
                    mean_exp = 0.0
                mean_exp_rounded = float(f"{mean_exp:.1f}")
                # Compare with tolerance of exact one decimal
                if float(f"{float(mean_stat):.1f}") == mean_exp_rounded:
                    scores["stats_summary_word_count_mean_correct"] = 1.0
        except Exception:
            pass

        # missing_publication_year_count
        try:
            missing_pub_year_stat = int(stats.get("missing_publication_year_count"))
        except Exception:
            missing_pub_year_stat = None
        if missing_pub_year_stat == missing_pub_year_exp:
            scores["stats_missing_publication_year_count_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()