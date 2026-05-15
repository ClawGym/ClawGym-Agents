import json
import csv
import sys;
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import urlparse
from datetime import datetime


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_json_load(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def safe_jsonl_load(path: Path) -> Optional[List[dict]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def parse_watchlist_yaml(path: Path) -> Tuple[Optional[List[str]], Optional[int]]:
    """
    Minimal YAML parser for config/watchlist.yaml, extracting:
    - search.allowed_domains (list of strings)
    - search.max_candidates (int)
    Returns (allowed_domains, max_candidates) or (None, None) on failure.
    """
    text = read_text(path)
    if text is None:
        return None, None
    lines = text.splitlines()
    in_search = False
    allowed_domains: List[str] = []
    max_candidates: Optional[int] = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if not in_search:
            if re.match(r'^\s*search:\s*$', line):
                in_search = True
                i += 1
                continue
        else:
            # Detect end of search section on new top-level key (e.g., output:)
            if re.match(r'^\S', line) and re.match(r'^\w.*:\s*$', line):
                in_search = False
                continue
            # parse allowed_domains
            m_allowed = re.match(r'^\s*allowed_domains\s*:\s*$', line)
            if m_allowed:
                j = i + 1
                while j < len(lines):
                    lm = lines[j]
                    if re.match(r'^\s*-\s+', lm):
                        m_item = re.match(r'^\s*-\s+(.*)$', lm)
                        if m_item:
                            val = m_item.group(1).strip()
                            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                                val = val[1:-1]
                            if val:
                                allowed_domains.append(val)
                        j += 1
                    else:
                        break
                i = j
                continue
            # parse max_candidates
            m_max = re.match(r'^\s*max_candidates\s*:\s*(\d+)\s*$', line)
            if m_max:
                try:
                    max_candidates = int(m_max.group(1))
                except Exception:
                    max_candidates = None
                i += 1
                continue
        i += 1
    return (allowed_domains if allowed_domains else None, max_candidates)


def is_iso8601_like(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s_norm = s.replace("Z", "+00:00") if s.endswith("Z") else s
        datetime.fromisoformat(s_norm)
        return True
    except Exception:
        return False


def safe_csv_read(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, []
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None


def extract_hostname(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if host is None:
            return None
        return host.lower()
    except Exception:
        return None


def word_count(text: str) -> int:
    return len(re.findall(r'\b\w+\b', text))


def single_paragraph(text: str) -> bool:
    lines = text.splitlines()
    paragraphs = []
    current = []
    for ln in lines:
        if ln.strip() == "":
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(ln)
    if current:
        paragraphs.append("\n".join(current))
    return len(paragraphs) == 1


def load_dossier_json(path: Path) -> Optional[dict]:
    data = safe_json_load(path)
    if not isinstance(data, dict):
        return None
    return data


def compare_unordered_list(a: List[Any], b: List[Any]) -> bool:
    try:
        from collections import Counter
        return Counter(a) == Counter(b)
    except Exception:
        return sorted(map(str, a)) == sorted(map(str, b))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    # Paths
    config_path = workspace / "config" / "watchlist.yaml"
    findings_json_path = workspace / "outputs" / "findings" / "cases_findings.json"
    summary_csv_path = workspace / "outputs" / "summary" / "cases_summary.csv"
    alert_txt_path = workspace / "outputs" / "alerts" / "cases_alert.txt"
    incoming_jsonl_path = workspace / "incoming" / "cases.jsonl"

    scores: Dict[str, float] = {
        "config_updated_allowed_domains": 0.0,
        "config_max_candidates_3": 0.0,
        "findings_json_structure": 0.0,
        "json_allowed_domains_match_config": 0.0,
        "json_cases_match_input": 0.0,
        "candidates_domains_and_limits_respected": 0.0,
        "csv_summary_matches_json_candidates": 0.0,
        "alert_text_requirements": 0.0,
    }

    # Parse config
    allowed_domains_config, max_candidates_config = parse_watchlist_yaml(config_path)

    # Check allowed domains include required additions
    if isinstance(allowed_domains_config, list):
        ad_lower = [d.strip().lower() for d in allowed_domains_config]
        required = {"sec.gov", "justice.gov", "cftc.gov"}
        if required.issubset(set(ad_lower)):
            scores["config_updated_allowed_domains"] = 1.0

    # Check max_candidates set to 3
    if isinstance(max_candidates_config, int) and max_candidates_config == 3:
        scores["config_max_candidates_3"] = 1.0

    # Load findings JSON
    dossier = load_dossier_json(findings_json_path)
    dossier_ok = False
    if isinstance(dossier, dict):
        processed_file = dossier.get("processed_file")
        processed_at = dossier.get("processed_at")
        allowed_domains_json = dossier.get("allowed_domains")
        cases = dossier.get("cases")
        if (
            processed_file == "incoming/cases.jsonl"
            and isinstance(allowed_domains_json, list)
            and isinstance(cases, list)
            and is_iso8601_like(processed_at if isinstance(processed_at, str) else "")
        ):
            dossier_ok = True
            scores["findings_json_structure"] = 1.0

    # Compare JSON allowed_domains to config allowed_domains
    if dossier_ok and isinstance(allowed_domains_config, list):
        ad_conf = sorted([d.strip().lower() for d in allowed_domains_config])
        ad_json = dossier.get("allowed_domains", [])
        if isinstance(ad_json, list):
            ad_json_l = sorted([str(d).strip().lower() for d in ad_json])
            if ad_conf == ad_json_l:
                scores["json_allowed_domains_match_config"] = 1.0

    # Check cases in JSON correspond to input JSONL
    input_cases = safe_jsonl_load(incoming_jsonl_path)
    if dossier_ok and isinstance(input_cases, list):
        dossier_cases_list = dossier.get("cases", [])
        if isinstance(dossier_cases_list, list):
            if len(dossier_cases_list) == len(input_cases):
                brief_to_case: Dict[str, dict] = {}
                all_unique = True
                for c in dossier_cases_list:
                    if not isinstance(c, dict):
                        all_unique = False
                        break
                    bn = c.get("brief_name")
                    if not isinstance(bn, str):
                        all_unique = False
                        break
                    if bn in brief_to_case:
                        all_unique = False
                        break
                    brief_to_case[bn] = c
                if all_unique:
                    all_match = True
                    for inp in input_cases:
                        bn = inp.get("brief_name")
                        kw = inp.get("keywords")
                        if not isinstance(bn, str) or not isinstance(kw, list):
                            all_match = False
                            break
                        case_obj = brief_to_case.get(bn)
                        if not isinstance(case_obj, dict):
                            all_match = False
                            break
                        q_terms = case_obj.get("query_terms")
                        if not isinstance(q_terms, list):
                            all_match = False
                            break
                        if not compare_unordered_list([str(x) for x in q_terms], [str(x) for x in kw]):
                            all_match = False
                            break
                    if all_match:
                        scores["json_cases_match_input"] = 1.0

    # Candidates domains and limits respected
    if dossier_ok and isinstance(allowed_domains_config, list) and isinstance(max_candidates_config, int):
        allowed_set = set([d.strip().lower() for d in allowed_domains_config])
        cases_list = dossier.get("cases", [])
        limits_ok = True
        for case in cases_list:
            if not isinstance(case, dict):
                limits_ok = False
                break
            cand_list = case.get("candidates", [])
            if not isinstance(cand_list, list):
                limits_ok = False
                break
            if len(cand_list) > max_candidates_config:
                limits_ok = False
                break
            for cand in cand_list:
                if not isinstance(cand, dict):
                    limits_ok = False
                    break
                required_fields = ["source_domain", "title", "url", "published_date", "retrieved_at"]
                if any(field not in cand for field in required_fields):
                    limits_ok = False
                    break
                sd = cand.get("source_domain")
                title = cand.get("title")
                url = cand.get("url")
                pub_date = cand.get("published_date")
                retrieved_at = cand.get("retrieved_at")
                if not (isinstance(sd, str) and isinstance(title, str) and isinstance(url, str) and isinstance(pub_date, str) and isinstance(retrieved_at, str)):
                    limits_ok = False
                    break
                if not is_iso8601_like(retrieved_at):
                    limits_ok = False
                    break
                sd_l = sd.strip().lower()
                if sd_l not in allowed_set:
                    limits_ok = False
                    break
                host = extract_hostname(url)
                if host is None:
                    limits_ok = False
                    break
                if not any(host.endswith(ad) for ad in allowed_set):
                    limits_ok = False
                    break
                if not host.endswith(sd_l):
                    limits_ok = False
                    break
            if not limits_ok:
                break
        if limits_ok:
            scores["candidates_domains_and_limits_respected"] = 1.0

    # CSV summary matches JSON candidates
    if dossier_ok:
        header, rows = safe_csv_read(summary_csv_path)
        if header is not None and rows is not None:
            expected_header = ["brief_name", "source_domain", "title", "url", "published_date", "retrieved_at"]
            if header == expected_header:
                cases_list = dossier.get("cases", [])
                expected_set = set()
                total_candidates = 0
                for case in cases_list:
                    if not isinstance(case, dict):
                        expected_set = None
                        break
                    bn = case.get("brief_name")
                    if not isinstance(bn, str):
                        expected_set = None
                        break
                    cand_list = case.get("candidates", [])
                    if not isinstance(cand_list, list):
                        expected_set = None
                        break
                    for cand in cand_list:
                        if not isinstance(cand, dict):
                            expected_set = None
                            break
                        sd = cand.get("source_domain", "")
                        title = cand.get("title", "")
                        url = cand.get("url", "")
                        pub_date = cand.get("published_date", "")
                        ra = cand.get("retrieved_at", "")
                        expected_set.add((bn, sd, title, url, pub_date, ra))
                        total_candidates += 1
                    if expected_set is None:
                        break
                if expected_set is not None:
                    rows_tuples = set(tuple(r) for r in rows)
                    if len(rows) == total_candidates and rows_tuples == expected_set:
                        scores["csv_summary_matches_json_candidates"] = 1.0

    # Alert text requirements
    alert_text = read_text(alert_txt_path)
    if alert_text is not None:
        text = alert_text.strip()
        lower = text.lower()
        single_para = single_paragraph(text)
        wc = word_count(text)
        has_official = "official" in lower
        has_allowed_domains_phrase = "allowed domain" in lower
        has_consult = "consult" in lower
        mentions_cases_stem = re.search(r'\bcases\b', lower) is not None
        mentions_json_path = "outputs/findings/cases_findings.json" in text
        mentions_csv_path = "outputs/summary/cases_summary.csv" in text
        if all([single_para, wc <= 90, has_official, has_allowed_domains_phrase, has_consult, mentions_cases_stem, mentions_json_path, mentions_csv_path]):
            scores["alert_text_requirements"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()