import sys
import json
import csv
import re
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing:{path}"
        return path.read_text(encoding="utf-8", errors="replace"), None
    except Exception as e:
        return None, f"error:{e}"


def _safe_load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing:{path}"
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows, None
    except Exception as e:
        return None, f"error:{e}"


def _safe_load_jsonl(path: Path) -> Tuple[Optional[List[Dict]], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing:{path}"
        items = []
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        items.append(obj)
                    else:
                        return None, f"non_dict_line:{i}"
                except Exception as e:
                    return None, f"json_error_line_{i}:{e}"
        return items, None
    except Exception as e:
        return None, f"error:{e}"


def _parse_int_or_none(v: str) -> Optional[int]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.upper() == "NA":
        return None
    try:
        return int(s)
    except Exception:
        return None


def _parse_http_status(v: str) -> Optional[int]:
    return _parse_int_or_none(v)


def _extract_hostname_and_tld(url: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        s = (url or "").strip()
        parts = urlsplit(s)
        host = parts.hostname
        if host is None:
            # attempt to add http:// for schemeless URLs
            parts2 = urlsplit("http://" + s)
            host = parts2.hostname
        if host is None:
            return None, None
        host = host.strip("[]").lower()
        if "." in host:
            tld = host.split(".")[-1]
        else:
            tld = host
        return host, tld
    except Exception:
        return None, None


def _split_keywords(kw_str: str) -> List[str]:
    if kw_str is None:
        return []
    return [k.strip() for k in str(kw_str).split(";") if k.strip()]


def _matched_keywords_in_url(url: str, keywords: List[str]) -> List[str]:
    url_l = (url or "").lower()
    hits = []
    for kw in keywords:
        if kw and kw.lower() in url_l:
            hits.append(kw)
    # deduplicate preserving order of first appearance
    seen = set()
    out = []
    for k in hits:
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            out.append(k)
    return out


def _classify_error_category(curl_exit_code: Optional[int], http_status: Optional[int]) -> str:
    if curl_exit_code in (35, 60):
        return "ssl_error"
    if curl_exit_code == 6:
        return "dns_error"
    if curl_exit_code == 28:
        return "timeout"
    if curl_exit_code == 0:
        if isinstance(http_status, int):
            if 200 <= http_status <= 299:
                return "success"
            if 300 <= http_status <= 399:
                return "redirect"
            if 400 <= http_status <= 499:
                return "client_error"
            if 500 <= http_status <= 599:
                return "server_error"
    return "other"


def _availability_score_from_category(cat: str) -> int:
    if cat == "success":
        return 2
    if cat == "redirect":
        return 1
    return 0


def _is_iso_timestamp(s: str) -> bool:
    try:
        if s.endswith("Z"):
            _ = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            _ = datetime.fromisoformat(s)
        return True
    except Exception:
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        return bool(re.match(pattern, s))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "required_outputs_exist": 0.0,
        "search_logs_per_target": 0.0,
        "min_urls_per_target": 0.0,
        "candidates_per_target_within_1_to_3": 0.0,
        "sources_no_duplicates_per_target": 0.0,
        "sources_raw_structure_and_consistency": 0.0,
        "fetch_results_structure_and_classification": 0.0,
        "fetch_results_cover_all_sources": 0.0,
        "fetch_log_includes_all_urls": 0.0,
        "sources_ranked_join_and_order": 0.0,
        "summary_covers_top_rank_per_target": 0.0,
    }

    # Load inputs
    targets_csv_path = workspace / "input" / "targets.csv"
    targets_rows, _ = _safe_load_csv_dicts(targets_csv_path)
    targets: Dict[str, Dict[str, object]] = {}
    if targets_rows and isinstance(targets_rows, list) and len(targets_rows) > 0:
        required_target_cols = {"target_id", "description", "org_hints", "official_domain_keywords", "min_sources"}
        have_cols = set(targets_rows[0].keys())
        if required_target_cols.issubset(have_cols):
            for r in targets_rows:
                tid = str(r.get("target_id", "")).strip()
                if not tid:
                    continue
                targets[tid] = {
                    "official_domain_keywords": r.get("official_domain_keywords", ""),
                    "min_sources": _parse_int_or_none(r.get("min_sources", "")) or 0,
                }

    # Check required outputs exist and are non-empty
    required_paths = [
        workspace / "logs" / "search_log.jsonl",
        workspace / "logs" / "fetch_log.txt",
        workspace / "results" / "fetch_results.csv",
        workspace / "results" / "sources_raw.csv",
        workspace / "results" / "sources_ranked.csv",
        workspace / "results" / "summary.md",
    ]
    all_exist = True
    for p in required_paths:
        try:
            if not (p.exists() and p.is_file() and p.stat().st_size > 0):
                all_exist = False
                break
        except Exception:
            all_exist = False
            break
    if all_exist:
        scores["required_outputs_exist"] = 1.0

    # Load produced artifacts
    search_log_path = workspace / "logs" / "search_log.jsonl"
    search_logs, _ = _safe_load_jsonl(search_log_path)
    fetch_log_text, _ = _safe_read_text(workspace / "logs" / "fetch_log.txt")
    fetch_results_rows, _ = _safe_load_csv_dicts(workspace / "results" / "fetch_results.csv")
    sources_raw_rows, _ = _safe_load_csv_dicts(workspace / "results" / "sources_raw.csv")
    sources_ranked_rows, _ = _safe_load_csv_dicts(workspace / "results" / "sources_ranked.csv")
    summary_text, _ = _safe_read_text(workspace / "results" / "summary.md")

    # Validate search logs
    def validate_search_logs() -> bool:
        if not targets or not search_logs:
            return False
        required_fields = {"target_id", "search_engine", "query", "timestamp_iso", "notes"}
        per_target_count: Dict[str, int] = {tid: 0 for tid in targets.keys()}
        for obj in search_logs:
            if not isinstance(obj, dict):
                return False
            if not required_fields.issubset(set(obj.keys())):
                return False
            tid = str(obj.get("target_id", "")).strip()
            if tid in per_target_count:
                # Field validations
                ts = str(obj.get("timestamp_iso", "")).strip()
                if not _is_iso_timestamp(ts):
                    return False
                if not str(obj.get("search_engine", "")).strip():
                    return False
                if not str(obj.get("query", "")).strip():
                    return False
                per_target_count[tid] += 1
        # ensure at least one query per target
        for tid, cnt in per_target_count.items():
            if cnt < 1:
                return False
        return True

    if validate_search_logs():
        scores["search_logs_per_target"] = 1.0

    # Validate sources_raw fields and consistency
    def validate_sources_raw() -> Tuple[bool, Dict[str, int], Dict[Tuple[str, str], Dict]]:
        if not targets or not sources_raw_rows:
            return False, {}, {}
        required_cols = {"target_id", "discovered_url", "domain", "tld", "source_org_guess", "matched_keywords", "official_match"}
        have_cols = set(sources_raw_rows[0].keys())
        if not required_cols.issubset(have_cols):
            return False, {}, {}
        counts_per_target: Dict[str, int] = {tid: 0 for tid in targets.keys()}
        rows_by_key: Dict[Tuple[str, str], Dict] = {}
        for row in sources_raw_rows:
            tid = str(row.get("target_id", "")).strip()
            url = str(row.get("discovered_url", "")).strip()
            dom = str(row.get("domain", "")).strip().lower()
            tld = str(row.get("tld", "")).strip().lower()
            mk_cell = str(row.get("matched_keywords", "")).strip()
            off_match_cell = str(row.get("official_match", "")).strip()
            if not tid or tid not in targets:
                return False, {}, {}
            if not url:
                return False, {}, {}
            # recompute domain/tld
            h, t = _extract_hostname_and_tld(url)
            if h is None or t is None:
                return False, {}, {}
            if dom != h or tld != t:
                return False, {}, {}
            # matched keywords from official_domain_keywords
            kws = _split_keywords(targets[tid]["official_domain_keywords"])
            hits = _matched_keywords_in_url(url, kws)
            mk_list = [x.strip() for x in mk_cell.split(";") if x.strip()]
            mk_set = set(x.lower() for x in mk_list)
            hits_set = set(x.lower() for x in hits)
            if mk_set != hits_set:
                return False, {}, {}
            # official_match 0/1
            try:
                off_val = int(off_match_cell)
            except Exception:
                return False, {}, {}
            if off_val not in (0, 1):
                return False, {}, {}
            expected_off = 1 if len(hits) > 0 else 0
            if off_val != expected_off:
                return False, {}, {}
            counts_per_target[tid] = counts_per_target.get(tid, 0) + 1
            rows_by_key[(tid, url)] = row
        return True, counts_per_target, rows_by_key

    raw_valid, counts_per_target, raw_rows_by_key = validate_sources_raw()
    if raw_valid:
        scores["sources_raw_structure_and_consistency"] = 1.0

    # Validate min URLs and bounds (1-3), and duplicates avoidance
    def validate_counts_and_duplicates() -> Tuple[bool, bool, bool]:
        if not targets or not sources_raw_rows:
            return False, False, False
        min_ok = True
        within_bounds_ok = True
        no_dups_ok = True
        # counts per target and duplicates per target
        by_target_urls: Dict[str, List[str]] = {tid: [] for tid in targets.keys()}
        for row in sources_raw_rows:
            tid = str(row.get("target_id", "")).strip()
            url = str(row.get("discovered_url", "")).strip()
            if tid in by_target_urls and url:
                by_target_urls[tid].append(url)
        for tid, urls in by_target_urls.items():
            cnt = len(urls)
            min_required = int(targets[tid]["min_sources"])
            if cnt < min_required or cnt < 1:
                min_ok = False
            if cnt < 1 or cnt > 3:
                within_bounds_ok = False
            # duplicates within each target
            if len(set(urls)) != len(urls):
                no_dups_ok = False
        return min_ok, within_bounds_ok, no_dups_ok

    min_ok, within_bounds_ok, no_dups_ok = validate_counts_and_duplicates()
    if min_ok:
        scores["min_urls_per_target"] = 1.0
    if within_bounds_ok:
        scores["candidates_per_target_within_1_to_3"] = 1.0
    if no_dups_ok:
        scores["sources_no_duplicates_per_target"] = 1.0

    # Validate fetch_results structure and classification
    def validate_fetch_results() -> Tuple[bool, Dict[Tuple[str, str], Dict]]:
        if not fetch_results_rows:
            return False, {}
        required_cols = {"target_id", "discovered_url", "final_url", "http_status", "curl_exit_code", "error_category"}
        have_cols = set(fetch_results_rows[0].keys())
        if not required_cols.issubset(have_cols):
            return False, {}
        by_key: Dict[Tuple[str, str], Dict] = {}
        for row in fetch_results_rows:
            tid = str(row.get("target_id", "")).strip()
            url = str(row.get("discovered_url", "")).strip()
            final_url = str(row.get("final_url", "")).strip()
            http_status = _parse_http_status(row.get("http_status", ""))
            curl_exit = _parse_int_or_none(row.get("curl_exit_code", ""))
            cat = str(row.get("error_category", "")).strip()
            if not tid or not url or not final_url:
                return False, {}
            if curl_exit is None:
                return False, {}
            expected_cat = _classify_error_category(curl_exit, http_status)
            if cat != expected_cat:
                return False, {}
            by_key[(tid, url)] = row
        return True, by_key

    fetch_valid, fetch_by_key = validate_fetch_results()
    if fetch_valid:
        scores["fetch_results_structure_and_classification"] = 1.0

    # Validate fetch covers all discovered sources
    if fetch_valid and raw_valid:
        raw_keys = set(raw_rows_by_key.keys())
        fetch_keys = set(fetch_by_key.keys())
        if raw_keys.issubset(fetch_keys) and len(raw_keys) > 0:
            scores["fetch_results_cover_all_sources"] = 1.0

    # Validate fetch log includes all discovered URLs (raw command outputs appended)
    if isinstance(fetch_log_text, str) and fetch_log_text.strip() and raw_valid:
        covered = True
        for (tid, url) in raw_rows_by_key.keys():
            if url not in fetch_log_text:
                covered = False
                break
        if covered:
            scores["fetch_log_includes_all_urls"] = 1.0

    # Validate sources_ranked join and order
    def validate_ranked() -> bool:
        if not (fetch_valid and raw_valid and sources_ranked_rows and targets):
            return False
        # Required columns from join plus rank
        raw_cols = {"domain", "tld", "source_org_guess", "matched_keywords", "official_match"}
        fetch_cols = {"final_url", "http_status", "curl_exit_code", "error_category"}
        base_cols = {"target_id", "discovered_url", "rank"}
        have_cols = set(sources_ranked_rows[0].keys())
        if not base_cols.issubset(have_cols):
            return False
        if not raw_cols.issubset(have_cols):
            return False
        if not fetch_cols.issubset(have_cols):
            return False

        # Ranked rows must correspond exactly to all join keys
        join_keys = set(raw_rows_by_key.keys()) & set(fetch_by_key.keys())
        ranked_keys = [(str(r.get("target_id", "")).strip(), str(r.get("discovered_url", "")).strip()) for r in sources_ranked_rows]
        ranked_key_set = set(ranked_keys)
        if ranked_key_set != join_keys:
            return False

        # No duplicates per target in ranked
        seen_per_target: Dict[str, set] = {}
        for tid, url in ranked_keys:
            s = seen_per_target.setdefault(tid, set())
            if url in s:
                return False
            s.add(url)

        # Validate per-target ordering and rank sequence
        rows_by_target: Dict[str, List[Dict]] = {}
        for row in sources_ranked_rows:
            tid = str(row.get("target_id", "")).strip()
            rows_by_target.setdefault(tid, []).append(row)

        for tid in targets.keys():
            group_rows = rows_by_target.get(tid, [])
            if not group_rows:
                return False
            # compute expected order keys: (-official_match, -availability_score, domain asc)
            tuples = []
            for row in group_rows:
                t = tid
                u = str(row.get("discovered_url", "")).strip()
                raw_row = raw_rows_by_key.get((t, u))
                fetch_row = fetch_by_key.get((t, u))
                if raw_row is None or fetch_row is None:
                    return False
                try:
                    off = int(str(raw_row.get("official_match", "0")).strip())
                except Exception:
                    return False
                curl_exit = _parse_int_or_none(fetch_row.get("curl_exit_code", ""))
                http_stat = _parse_http_status(fetch_row.get("http_status", ""))
                cat = _classify_error_category(curl_exit, http_stat)
                avail = _availability_score_from_category(cat)
                dom = str(raw_row.get("domain", "")).lower()
                tuples.append(((t, u), off, avail, dom))
            tuples_sorted = sorted(tuples, key=lambda x: (-x[1], -x[2], x[3]))
            expected_order = [k for (k, _, __, ___) in tuples_sorted]

            # sort provided by rank ascending and validate
            try:
                group_sorted = sorted(group_rows, key=lambda r: int(str(r.get("rank", "0")).strip()))
            except Exception:
                return False
            ranks_seq = [int(str(r.get("rank", "0")).strip()) for r in group_sorted]
            if ranks_seq != list(range(1, len(group_sorted) + 1)):
                return False
            actual_order = [(str(r.get("target_id", "")).strip(), str(r.get("discovered_url", "")).strip()) for r in group_sorted]
            if actual_order != expected_order:
                return False
        return True

    if validate_ranked():
        scores["sources_ranked_join_and_order"] = 1.0

    # Validate summary: top-ranked URL per target with error_category and justification mentioning matched keyword(s) if present
    def validate_summary() -> bool:
        if not (summary_text and isinstance(summary_text, str) and summary_text.strip() and sources_ranked_rows and targets):
            return False
        # Determine top-ranked row per target
        top_per_target: Dict[str, Dict] = {}
        for tid in targets.keys():
            rows_t = [r for r in sources_ranked_rows if str(r.get("target_id", "")).strip() == tid]
            if not rows_t:
                return False
            try:
                rows_t_sorted = sorted(rows_t, key=lambda r: int(str(r.get("rank", "0")).strip()))
            except Exception:
                return False
            top_per_target[tid] = rows_t_sorted[0]

        text = summary_text
        lines = text.splitlines()
        for tid, top in top_per_target.items():
            url = str(top.get("discovered_url", "")).strip()
            cat = str(top.get("error_category", "")).strip()
            if not url or not cat:
                return False
            # Look for a line mentioning the target_id and the URL
            candidate_lines = [ln for ln in lines if (tid in ln and url in ln)]
            if not candidate_lines:
                return False
            line = candidate_lines[0]
            # Ensure error_category is mentioned
            if cat not in line:
                return False
            # If matched_keywords present, ensure at least one appears
            mk = ""
            raw = raw_rows_by_key.get((tid, url))
            if raw:
                mk = str(raw.get("matched_keywords", "")).strip()
            if mk:
                kws = [k.strip() for k in mk.split(";") if k.strip()]
                if kws:
                    any_kw = any(k in line for k in kws)
                    if not any_kw:
                        return False
        return True

    if validate_summary():
        scores["summary_covers_top_rank_per_target"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()