import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse
from datetime import datetime


ALLOWED_SOURCE_TYPES = {"UNESCO", "JP_National", "KR_National", "CN_Gov", "OtherOfficial"}
ALLOWED_SITE_FILTERS = ["whc.unesco.org", "bunka.go.jp", "heritage.go.kr", "gov.cn"]


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_parse_jsonl(path: Path) -> Optional[List[dict]]:
    if not path.exists() or not path.is_file():
        return None
    lines = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if line == "":
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                lines.append(obj)
    except Exception:
        return None
    return lines


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    if not path.exists() or not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    s2 = s.strip()
    # Normalize 'Z' -> '+00:00'
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _normalize_domain_from_url(url: str) -> Optional[str]:
    try:
        p = urlparse(url)
        dom = p.netloc.lower()
        if ":" in dom:
            dom = dom.split(":", 1)[0]
        if dom.startswith("www."):
            dom = dom[4:]
        return dom
    except Exception:
        return None


def _normalize_domain_value(domain: str) -> str:
    d = (domain or "").strip().lower()
    if ":" in d:
        d = d.split(":", 1)[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def _classify_domain_to_source_type(domain: str) -> Optional[str]:
    d = _normalize_domain_value(domain)
    if not d:
        return None
    if "whc.unesco.org" in d:
        return "UNESCO"
    if d.endswith("bunka.go.jp"):
        return "JP_National"
    if d.endswith("heritage.go.kr"):
        return "KR_National"
    if d.endswith("gov.cn"):
        return "CN_Gov"
    return "OtherOfficial"


def _slugify(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"[^\w]+", "-", t)
    t = re.sub(r"-{2,}", "-", t)
    return t.strip("-")


def _collect_raw_html_files(raw_dir: Path) -> List[Path]:
    if not raw_dir.exists():
        return []
    files = []
    for p in raw_dir.rglob("*.html"):
        if p.is_file():
            files.append(p)
    for p in raw_dir.rglob("*.htm"):
        if p.is_file():
            files.append(p)
    return files


def _csv_required_columns(path: Path, required: List[str]) -> Tuple[bool, Optional[List[Dict[str, str]]]]:
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return False, None
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return False, None
    if header is None:
        return False, None
    if header != required:
        return False, None
    return True, rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_exists": 0.0,
        "queries_log_valid": 0.0,
        "queries_per_landmark_with_site_filter": 0.0,
        "coverage_for_all_landmarks_in_logs": 0.0,
        "pages_jsonl_valid": 0.0,
        "domain_matches_url_ratio": 0.0,
        "source_type_consistency_ratio": 0.0,
        "first_paragraph_length_ratio": 0.0,
        "fetch_timestamp_iso_ratio": 0.0,
        "page_to_html_traceability_ratio": 0.0,
        "pages_per_landmark_limit_respected": 0.0,
        "pages_landmarks_subset_of_input": 0.0,
        "summary_csv_structure_valid": 0.0,
        "coverage_for_all_landmarks_in_summary": 0.0,
        "summary_counts_match_pages": 0.0,
        "status_report_quality": 0.0,
    }

    # Load input landmarks
    input_csv = workspace / "input" / "landmarks.csv"
    input_rows = _safe_read_csv_dicts(input_csv)
    input_landmarks = []
    if input_rows:
        for r in input_rows:
            lm = (r.get("landmark") or "").strip()
            country = (r.get("country") or "").strip()
            if lm and country:
                input_landmarks.append((lm, country))
    input_landmark_set = set(lm for lm, _ in input_landmarks)

    # 1) Script presence
    script_path = workspace / "scripts" / "fetch_official_pages.py"
    if script_path.exists() and script_path.is_file():
        try:
            content = script_path.read_text(encoding="utf-8", errors="ignore")
            if content.strip():
                scores["script_exists"] = 1.0
        except Exception:
            scores["script_exists"] = 0.0

    # 2) Parse logs/search_queries.jsonl
    logs_path = workspace / "logs" / "search_queries.jsonl"
    logs = _safe_parse_jsonl(logs_path)
    logs_valid = False
    if logs is not None and len(logs) > 0:
        per_line_valid = True
        for obj in logs:
            needed = ["landmark", "country", "query", "url", "rank", "timestamp"]
            if not all(k in obj for k in needed):
                per_line_valid = False
                break
            if not isinstance(obj.get("landmark"), str) or not isinstance(obj.get("country"), str):
                per_line_valid = False
                break
            if not isinstance(obj.get("query"), str) or not isinstance(obj.get("url"), str):
                per_line_valid = False
                break
            rank = obj.get("rank")
            if rank is not None and not isinstance(rank, int):
                per_line_valid = False
                break
            ts = obj.get("timestamp")
            if not isinstance(ts, str) or not _is_iso8601(ts):
                per_line_valid = False
                break
        if per_line_valid:
            logs_valid = True
            scores["queries_log_valid"] = 1.0

    # 2.a Coverage in logs: at least one log per input landmark
    if logs_valid and input_landmarks:
        covered = 0
        for lm, _country in input_landmarks:
            found = any((obj.get("landmark") or "") == lm for obj in logs)
            if found:
                covered += 1
        scores["coverage_for_all_landmarks_in_logs"] = covered / max(1, len(input_landmarks))
    else:
        scores["coverage_for_all_landmarks_in_logs"] = 0.0

    # 2.b At least one query per landmark with site filter to allowed domains
    if logs_valid and input_landmarks:
        lm_has_site = 0
        for lm, _country in input_landmarks:
            any_ok = False
            for obj in logs:
                if (obj.get("landmark") or "") != lm:
                    continue
                q = (obj.get("query") or "").lower()
                if "site:" in q:
                    for pat in ALLOWED_SITE_FILTERS:
                        if f"site:{pat}" in q:
                            any_ok = True
                            break
                if any_ok:
                    break
            if any_ok:
                lm_has_site += 1
        scores["queries_per_landmark_with_site_filter"] = lm_has_site / max(1, len(input_landmarks))
    else:
        scores["queries_per_landmark_with_site_filter"] = 0.0

    # 3) Parse data/pages.jsonl
    pages_path = workspace / "data" / "pages.jsonl"
    pages = _safe_parse_jsonl(pages_path)
    if pages is not None and len(pages) > 0:
        all_ok = True
        for obj in pages:
            required_keys = ["url", "domain", "page_title", "first_paragraph", "landmark", "country", "source_type", "fetch_timestamp"]
            if not all(k in obj for k in required_keys):
                all_ok = False
                break
            if not isinstance(obj.get("url"), str) or not isinstance(obj.get("domain"), str):
                all_ok = False
                break
            if not isinstance(obj.get("page_title"), str):
                all_ok = False
                break
            if not isinstance(obj.get("first_paragraph"), str):
                all_ok = False
                break
            if not isinstance(obj.get("landmark"), str) or not isinstance(obj.get("country"), str):
                all_ok = False
                break
            st = obj.get("source_type")
            if not isinstance(st, str) or st not in ALLOWED_SOURCE_TYPES:
                all_ok = False
                break
            ts = obj.get("fetch_timestamp")
            if not isinstance(ts, str) or not _is_iso8601(ts):
                all_ok = False
                break
            if "meta_description" in obj and obj["meta_description"] is not None and not isinstance(obj["meta_description"], str):
                all_ok = False
                break
        if all_ok:
            scores["pages_jsonl_valid"] = 1.0
        else:
            scores["pages_jsonl_valid"] = 0.0
    else:
        pages = None
        scores["pages_jsonl_valid"] = 0.0

    # 3.a Domain matches URL, source type consistency, first_paragraph length, fetch_timestamp ISO
    if pages is not None and len(pages) > 0 and scores["pages_jsonl_valid"] == 1.0:
        domain_match_count = 0
        st_consistent_count = 0
        fp_len_count = 0
        ts_count = 0
        for obj in pages:
            url = obj.get("url") or ""
            declared_domain = obj.get("domain") or ""
            normalized_url_domain = _normalize_domain_from_url(url) or ""
            normalized_declared = _normalize_domain_value(declared_domain)
            if normalized_declared == normalized_url_domain:
                domain_match_count += 1

            inferred_type = _classify_domain_to_source_type(normalized_declared) or "OtherOfficial"
            if obj.get("source_type") == inferred_type or (inferred_type == "OtherOfficial" and obj.get("source_type") == "OtherOfficial"):
                st_consistent_count += 1

            fp = obj.get("first_paragraph") or ""
            if isinstance(fp, str) and len(fp) <= 300 and len(fp.strip()) > 0:
                fp_len_count += 1

            ts = obj.get("fetch_timestamp") or ""
            if _is_iso8601(ts):
                ts_count += 1

        total = len(pages)
        scores["domain_matches_url_ratio"] = domain_match_count / total
        scores["source_type_consistency_ratio"] = st_consistent_count / total
        scores["first_paragraph_length_ratio"] = fp_len_count / total
        scores["fetch_timestamp_iso_ratio"] = ts_count / total
    else:
        scores["domain_matches_url_ratio"] = 0.0
        scores["source_type_consistency_ratio"] = 0.0
        scores["first_paragraph_length_ratio"] = 0.0
        scores["fetch_timestamp_iso_ratio"] = 0.0

    # 3.b Traceability to raw HTML files
    raw_dir = workspace / "data" / "raw_html"
    raw_files = _collect_raw_html_files(raw_dir)
    if pages is not None and len(pages) > 0 and raw_files:
        matched = 0
        for obj in pages:
            lm = _slugify(obj.get("landmark") or "")
            dom = _normalize_domain_value(obj.get("domain") or "")
            found_file = False
            for f in raw_files:
                name = f.name.lower()
                if dom and dom in name:
                    if lm and lm in name:
                        found_file = True
                        break
            if found_file:
                matched += 1
        scores["page_to_html_traceability_ratio"] = matched / max(1, len(pages))
    else:
        scores["page_to_html_traceability_ratio"] = 0.0

    # 3.c Pages per landmark limit respected (<=3 per landmark)
    if pages is not None:
        if len(pages) == 0 and input_landmarks:
            scores["pages_per_landmark_limit_respected"] = 1.0
        elif len(pages) >= 0 and input_landmarks:
            counts = {}
            for obj in pages:
                lm = obj.get("landmark") or ""
                counts[lm] = counts.get(lm, 0) + 1
            ok = 0
            for lm, _country in input_landmarks:
                if counts.get(lm, 0) <= 3:
                    ok += 1
            scores["pages_per_landmark_limit_respected"] = ok / max(1, len(input_landmarks))
        else:
            scores["pages_per_landmark_limit_respected"] = 0.0
    else:
        scores["pages_per_landmark_limit_respected"] = 0.0

    # 3.d Pages landmarks subset of input
    if pages is not None:
        if len(pages) == 0:
            scores["pages_landmarks_subset_of_input"] = 1.0 if input_landmarks else 0.0
        elif input_landmarks:
            total = len(pages)
            subset_ok = 0
            for obj in pages:
                lm = obj.get("landmark") or ""
                if lm in input_landmark_set:
                    subset_ok += 1
            scores["pages_landmarks_subset_of_input"] = subset_ok / total
        else:
            scores["pages_landmarks_subset_of_input"] = 0.0
    else:
        scores["pages_landmarks_subset_of_input"] = 0.0

    # 4) data/landmarks_summary.csv structure and content
    summary_path = workspace / "data" / "landmarks_summary.csv"
    required_cols = [
        "landmark",
        "country",
        "pages_total",
        "pages_unesco",
        "pages_jp_national",
        "pages_kr_national",
        "pages_cn_gov",
        "pages_other_official",
        "has_official",
        "sample_snippet",
    ]
    summary_ok, summary_rows = _csv_required_columns(summary_path, required_cols)
    if summary_ok and summary_rows is not None:
        scores["summary_csv_structure_valid"] = 1.0
        # Coverage for all landmarks in summary
        if input_landmarks:
            seen = {}
            for r in summary_rows:
                lm = (r.get("landmark") or "").strip()
                seen[lm] = seen.get(lm, 0) + 1
            covered = 0
            duplicates = False
            for lm, _c in input_landmarks:
                count = seen.get(lm, 0)
                if count == 1:
                    covered += 1
                elif count > 1:
                    duplicates = True
            if duplicates:
                scores["coverage_for_all_landmarks_in_summary"] = covered / max(1, len(input_landmarks)) * 0.5
            else:
                scores["coverage_for_all_landmarks_in_summary"] = covered / max(1, len(input_landmarks))
        else:
            scores["coverage_for_all_landmarks_in_summary"] = 0.0

        # Compare counts with pages.jsonl
        if pages is not None:
            counts_map: Dict[str, Dict[str, int]] = {}
            for lm, _c in input_landmarks:
                counts_map[lm] = {
                    "UNESCO": 0,
                    "JP_National": 0,
                    "KR_National": 0,
                    "CN_Gov": 0,
                    "OtherOfficial": 0,
                }
            for obj in pages:
                lm = obj.get("landmark") or ""
                st = obj.get("source_type") or ""
                if lm in counts_map and st in counts_map[lm]:
                    counts_map[lm][st] += 1
            match_count = 0
            total_landmarks = 0
            for r in summary_rows:
                lm = (r.get("landmark") or "").strip()
                if lm not in input_landmark_set:
                    continue
                total_landmarks += 1
                try:
                    pages_unesco = int(r.get("pages_unesco") or 0)
                    pages_jp = int(r.get("pages_jp_national") or 0)
                    pages_kr = int(r.get("pages_kr_national") or 0)
                    pages_cn = int(r.get("pages_cn_gov") or 0)
                    pages_other = int(r.get("pages_other_official") or 0)
                    pages_total = int(r.get("pages_total") or 0)
                except Exception:
                    continue
                counts = counts_map.get(lm, {"UNESCO": 0, "JP_National": 0, "KR_National": 0, "CN_Gov": 0, "OtherOfficial": 0})
                expected_unesco = counts.get("UNESCO", 0)
                expected_jp = counts.get("JP_National", 0)
                expected_kr = counts.get("KR_National", 0)
                expected_cn = counts.get("CN_Gov", 0)
                expected_other = counts.get("OtherOfficial", 0)
                expected_total = expected_unesco + expected_jp + expected_kr + expected_cn + expected_other
                has_official = (r.get("has_official") or "").strip().lower()
                has_official_bool = has_official in ["true", "1", "yes", "y", "t"]
                snippet = (r.get("sample_snippet") or "").strip()
                snippet_ok = (expected_total == 0 and snippet == "") or (expected_total > 0 and len(snippet) > 0)
                if (
                    pages_unesco == expected_unesco
                    and pages_jp == expected_jp
                    and pages_kr == expected_kr
                    and pages_cn == expected_cn
                    and pages_other == expected_other
                    and pages_total == expected_total
                    and (has_official_bool == (expected_total > 0))
                    and snippet_ok
                ):
                    match_count += 1
            if total_landmarks > 0:
                scores["summary_counts_match_pages"] = match_count / total_landmarks
            else:
                scores["summary_counts_match_pages"] = 0.0
        else:
            scores["summary_counts_match_pages"] = 0.0
    else:
        scores["summary_csv_structure_valid"] = 0.0
        scores["coverage_for_all_landmarks_in_summary"] = 0.0
        scores["summary_counts_match_pages"] = 0.0

    # 5) reports/status_report.md content quality
    report_path = workspace / "reports" / "status_report.md"
    content = _safe_read_text(report_path)
    if content is not None:
        conds = []

        conds.append(True)

        paragraphs = [p for p in re.split(r"\n\s*\n", content) if p.strip()]
        conds.append(len(paragraphs) >= 1)

        next_steps_idx = None
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "next steps" in line.lower():
                next_steps_idx = i
                break
        conds.append(next_steps_idx is not None)

        bullets_after = 0
        if next_steps_idx is not None:
            for j in range(next_steps_idx + 1, len(lines)):
                l = lines[j].strip()
                if l == "":
                    if bullets_after > 0:
                        break
                    else:
                        continue
                if re.match(r"^[-*]\s+", l) or re.match(r"^\d+\.\s+", l):
                    bullets_after += 1
                else:
                    if bullets_after > 0:
                        break
        conds.append(bullets_after >= 2)

        if input_landmarks:
            all_mentioned = True
            lowered = content.lower()
            for lm, _c in input_landmarks:
                if lm.lower() not in lowered:
                    all_mentioned = False
                    break
            conds.append(all_mentioned)
        else:
            conds.append(False)

        conds.append(("unesco" in content.lower()) or ("national" in content.lower()))

        score = sum(1.0 for c in conds if c) / float(len(conds))
        scores["status_report_quality"] = score
    else:
        scores["status_report_quality"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()