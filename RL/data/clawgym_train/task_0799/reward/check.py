import json
import csv
import sys
import re
import os
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Tuple[bool, Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return False, None
        return True, json.loads(text)
    except Exception:
        return False, None


def _is_iso8601(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    s = value
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def _normalize_domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.netloc
        if not host and parsed.path:
            parsed2 = urlparse("http://" + url)
            host = parsed2.netloc
        if not host:
            return None
        if "@" in host:
            host = host.split("@", 1)[-1]
        if ":" in host:
            host = host.split(":", 1)[0]
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return None


def _normalize_domain_literal(domain: str) -> str:
    d = domain.strip().lower()
    if d.startswith("www."):
        d = d[4:]
    return d


def _parse_projects_csv(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    text = _safe_read_text(path)
    if text is None:
        return False, []
    try:
        reader = csv.DictReader(text.splitlines())
        expected_header = ["name", "ticker", "allowed_domains"]
        if reader.fieldnames != expected_header:
            return False, []
        projects = []
        for row in reader:
            name = (row.get("name") or "").strip()
            ticker = (row.get("ticker") or "").strip()
            allowed = (row.get("allowed_domains") or "").strip()
            if not name or not ticker or not allowed:
                return False, []
            projects.append(
                {
                    "name": name,
                    "ticker": ticker,
                    "ticker_lower": ticker.lower(),
                    "allowed_domain": _normalize_domain_literal(allowed),
                }
            )
        if not projects:
            return False, []
        return True, projects
    except Exception:
        return False, []


def _load_official_sites_json(path: Path) -> Tuple[bool, Any]:
    ok, data = _safe_load_json(path)
    if not ok or not isinstance(data, list):
        return False, None
    return True, data


def _index_by_ticker(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx = {}
    for rec in items:
        t = rec.get("ticker")
        if isinstance(t, str):
            idx[t.upper()] = rec
    return idx


def _parse_csv_file(path: Path) -> Tuple[bool, List[Dict[str, str]], Optional[List[str]]]:
    text = _safe_read_text(path)
    if text is None:
        return False, [], None
    try:
        reader = csv.DictReader(text.splitlines())
        rows = [row for row in reader]
        return True, rows, reader.fieldnames
    except Exception:
        return False, [], None


def _csv_fieldnames_exact(fieldnames: Optional[List[str]], expected: List[str]) -> bool:
    return fieldnames == expected


def _csv_str_to_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = value.strip()
    if v == "" or v.lower() == "null":
        return None
    return v


def _has_executable_bit(path: Path) -> bool:
    try:
        return path.exists() and os.access(str(path), os.X_OK)
    except Exception:
        return False


def _find_fetch_log_lines_for_ticker(log_text: str, ticker: str) -> List[str]:
    lines = []
    for line in log_text.splitlines():
        if ticker.lower() in line.lower():
            lines.append(line)
    return lines


def _line_has_two_urls_and_status(line: str) -> bool:
    urls = re.findall(r"https?://\S+", line)
    status = re.search(r"\b([1-5][0-9]{2})\b", line)
    timestamp_like = "T" in line and ":" in line
    return len(urls) >= 2 and status is not None and timestamp_like


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "evidence_files_count_and_schema": 0.0,
        "structured_json_exists_and_schema": 0.0,
        "structured_json_records_match_input": 0.0,
        "search_counts_and_queries_consistency": 0.0,
        "official_url_domain_matches_allowed": 0.0,
        "source_domain_consistent_with_official_url": 0.0,
        "raw_html_files_exist_for_ok_status": 0.0,
        "fetch_log_lines_for_ok_status": 0.0,
        "csv_exists_and_schema": 0.0,
        "csv_json_row_consistency": 0.0,
        "validation_script_executable": 0.0,
        "tests_validation_report_present_and_well_formed": 0.0,
        "tests_validation_stdout_captured": 0.0,
    }

    projects_csv_path = workspace / "input" / "projects.csv"
    parsed_ok, projects = _parse_projects_csv(projects_csv_path)
    if not parsed_ok or not projects:
        return scores

    json_path = workspace / "data" / "structured" / "official_sites.json"
    json_ok, json_data = _load_official_sites_json(json_path)
    json_index: Dict[str, Dict[str, Any]] = {}
    if json_ok:
        json_index = _index_by_ticker(json_data)

    evidence_passes = 0
    evidence_total = len(projects)
    evidence_counts_by_ticker: Dict[str, int] = {}
    for proj in projects:
        ticker_lower = proj["ticker_lower"]
        evidence_path = workspace / "data" / "evidence" / f"search_results_{ticker_lower}.json"
        ok, ev = _safe_load_json(evidence_path)
        valid = False
        if ok and isinstance(ev, dict):
            query = ev.get("query")
            timestamp = ev.get("timestamp")
            results = ev.get("results")
            if isinstance(query, str) and _is_iso8601(timestamp) and isinstance(results, list) and len(results) >= 3:
                all_valid = True
                for r in results:
                    if not isinstance(r, dict):
                        all_valid = False
                        break
                    if not isinstance(r.get("rank"), int):
                        all_valid = False
                    if not isinstance(r.get("title"), str):
                        all_valid = False
                    if not isinstance(r.get("domain"), str):
                        all_valid = False
                    if not all_valid:
                        break
                if all_valid:
                    valid = True
                    evidence_counts_by_ticker[proj["ticker"].upper()] = len(results)
        if valid:
            evidence_passes += 1
    scores["evidence_files_count_and_schema"] = evidence_passes / evidence_total if evidence_total > 0 else 0.0

    if json_ok and isinstance(json_data, list):
        per_rec_passes = 0
        for proj in projects:
            tkr = proj["ticker"].upper()
            rec = json_index.get(tkr)
            valid = False
            if isinstance(rec, dict):
                name_ok = isinstance(rec.get("name"), str) and rec.get("name") == proj["name"]
                ticker_ok = isinstance(rec.get("ticker"), str) and rec.get("ticker").upper() == proj["ticker"].upper()
                ou = rec.get("official_url", None)
                ou_ok = (ou is None) or isinstance(ou, str)
                sd = rec.get("source_domain", None)
                sd_ok = (sd is None) or isinstance(sd, str)
                ht = rec.get("homepage_title", None)
                ht_ok = (ht is None) or isinstance(ht, str)
                fa = rec.get("fetched_at", None)
                fa_ok = (fa is None) or _is_iso8601(fa)
                sq = rec.get("search_queries", None)
                sq_ok = isinstance(sq, list) and all(isinstance(x, str) for x in sq)
                sc = rec.get("search_evidence_count", None)
                sc_ok = isinstance(sc, int)
                valid = name_ok and ticker_ok and ou_ok and sd_ok and ht_ok and fa_ok and sq_ok and sc_ok
            if valid:
                per_rec_passes += 1
        scores["structured_json_exists_and_schema"] = per_rec_passes / len(projects) if projects else 0.0
    else:
        scores["structured_json_exists_and_schema"] = 0.0

    if json_ok and isinstance(json_data, list):
        matched = 0
        for proj in projects:
            rec = json_index.get(proj["ticker"].upper())
            if rec and rec.get("name") == proj["name"] and rec.get("ticker", "").upper() == proj["ticker"].upper():
                matched += 1
        if matched == len(projects) and len(json_data) == len(projects):
            scores["structured_json_records_match_input"] = 1.0
        else:
            scores["structured_json_records_match_input"] = matched / len(projects) if projects else 0.0
    else:
        scores["structured_json_records_match_input"] = 0.0

    if json_ok and isinstance(json_data, list):
        consistency_passes = 0
        total = len(projects)
        for proj in projects:
            rec = json_index.get(proj["ticker"].upper())
            evidence_count = evidence_counts_by_ticker.get(proj["ticker"].upper())
            if isinstance(rec, dict) and isinstance(rec.get("search_queries"), list) and all(isinstance(x, str) for x in rec.get("search_queries")) and len(rec.get("search_queries")) >= 1 and isinstance(rec.get("search_evidence_count"), int) and evidence_count is not None and rec.get("search_evidence_count") == evidence_count:
                consistency_passes += 1
        scores["search_counts_and_queries_consistency"] = consistency_passes / total if total > 0 else 0.0
    else:
        scores["search_counts_and_queries_consistency"] = 0.0

    domain_match_passes = 0
    for proj in projects:
        rec = json_index.get(proj["ticker"].upper()) if json_index else None
        ok_match = True
        if isinstance(rec, dict):
            ou = rec.get("official_url", None)
            if ou is not None:
                dom = _normalize_domain_from_url(ou or "")
                ok_match = dom is not None and dom == proj["allowed_domain"]
        else:
            ok_match = False
        if ok_match:
            domain_match_passes += 1
    scores["official_url_domain_matches_allowed"] = domain_match_passes / len(projects) if projects else 0.0

    src_domain_passes = 0
    for proj in projects:
        rec = json_index.get(proj["ticker"].upper()) if json_index else None
        valid = False
        if isinstance(rec, dict):
            ou = rec.get("official_url", None)
            sd = rec.get("source_domain", None)
            if ou is None:
                valid = sd is None
            else:
                dom = _normalize_domain_from_url(ou or "")
                valid = dom is not None and isinstance(sd, str) and _normalize_domain_literal(sd) == dom
        if valid:
            src_domain_passes += 1
    scores["source_domain_consistent_with_official_url"] = src_domain_passes / len(projects) if projects else 0.0

    csv_path = workspace / "data" / "structured" / "official_sites.csv"
    csv_ok, csv_rows, csv_fields = _parse_csv_file(csv_path)
    expected_csv_header = ["name", "ticker", "official_url", "source_domain", "homepage_title", "fetched_at", "status"]
    if csv_ok and _csv_fieldnames_exact(csv_fields, expected_csv_header):
        scores["csv_exists_and_schema"] = 1.0
    else:
        scores["csv_exists_and_schema"] = 0.0

    if csv_ok and _csv_fieldnames_exact(csv_fields, expected_csv_header) and json_ok and isinstance(json_data, list):
        csv_index = {}
        for row in csv_rows:
            t = (row.get("ticker") or "").upper()
            if t:
                csv_index[t] = row
        consistency_passes = 0
        total = len(projects)
        for proj in projects:
            t = proj["ticker"].upper()
            csv_row = csv_index.get(t)
            rec = json_index.get(t)
            ok_consistent = False
            if csv_row and rec:
                name_ok = (csv_row.get("name") or "") == proj["name"]
                ticker_ok = (csv_row.get("ticker") or "").upper() == proj["ticker"].upper()
                csv_official_url = _csv_str_to_optional(csv_row.get("official_url"))
                csv_source_domain = _csv_str_to_optional(csv_row.get("source_domain"))
                csv_homepage_title = _csv_str_to_optional(csv_row.get("homepage_title"))
                csv_fetched_at = _csv_str_to_optional(csv_row.get("fetched_at"))

                json_official_url = rec.get("official_url", None)
                json_source_domain = rec.get("source_domain", None)
                json_homepage_title = rec.get("homepage_title", None)
                json_fetched_at = rec.get("fetched_at", None)

                ou_ok = (json_official_url if json_official_url is not None else None) == csv_official_url
                sd_ok = (json_source_domain if json_source_domain is not None else None) == csv_source_domain
                ht_ok = (json_homepage_title if json_homepage_title is not None else None) == csv_homepage_title
                fa_ok = (json_fetched_at if json_fetched_at is not None else None) == csv_fetched_at

                status = (csv_row.get("status") or "").lower()
                expected_status = "ok" if json_official_url is not None else "not_found"
                status_ok = status == expected_status

                ok_consistent = name_ok and ticker_ok and ou_ok and sd_ok and ht_ok and fa_ok and status_ok
            if ok_consistent:
                consistency_passes += 1
        scores["csv_json_row_consistency"] = consistency_passes / total if total > 0 else 0.0
    else:
        scores["csv_json_row_consistency"] = 0.0

    if csv_ok and _csv_fieldnames_exact(csv_fields, expected_csv_header):
        ok_rows = [row for row in csv_rows if (row.get("status") or "").lower() == "ok"]
        if len(ok_rows) == 0:
            scores["raw_html_files_exist_for_ok_status"] = 1.0
        else:
            ok_passes = 0
            for row in ok_rows:
                t_lower = (row.get("ticker") or "").lower()
                raw_path = workspace / "data" / "raw" / f"{t_lower}.html"
                content = _safe_read_text(raw_path)
                if content is not None and content.strip() != "":
                    ok_passes += 1
            scores["raw_html_files_exist_for_ok_status"] = ok_passes / len(ok_rows) if ok_rows else 0.0
    else:
        scores["raw_html_files_exist_for_ok_status"] = 0.0

    log_path = workspace / "logs" / "fetch.log"
    log_text = _safe_read_text(log_path) or ""
    if csv_ok and _csv_fieldnames_exact(csv_fields, expected_csv_header):
        ok_rows = [row for row in csv_rows if (row.get("status") or "").lower() == "ok"]
        if len(ok_rows) == 0:
            scores["fetch_log_lines_for_ok_status"] = 1.0
        else:
            passes = 0
            for row in ok_rows:
                t = (row.get("ticker") or "")
                ou = _csv_str_to_optional(row.get("official_url"))
                allowed_domain = None
                for proj in projects:
                    if proj["ticker"].upper() == t.upper():
                        allowed_domain = proj["allowed_domain"]
                        break
                lines = _find_fetch_log_lines_for_ticker(log_text, t)
                line_ok = False
                for ln in lines:
                    cond_base = _line_has_two_urls_and_status(ln)
                    cond_domain = True
                    if allowed_domain is not None:
                        cond_domain = allowed_domain in ln
                    cond_official = True
                    if ou is not None:
                        dom = _normalize_domain_from_url(ou) or ""
                        if dom:
                            cond_official = dom in ln
                    if cond_base and cond_domain and cond_official:
                        line_ok = True
                        break
                if line_ok:
                    passes += 1
            total_ok = len(ok_rows)
            scores["fetch_log_lines_for_ok_status"] = passes / total_ok if total_ok > 0 else 0.0
    else:
        scores["fetch_log_lines_for_ok_status"] = 0.0

    script_path = workspace / "scripts" / "validate_outputs.sh"
    scores["validation_script_executable"] = 1.0 if _has_executable_bit(script_path) else 0.0

    report_path = workspace / "tests" / "validation_report.json"
    ok_report, report_data = _safe_load_json(report_path)
    rep_valid = False
    if ok_report and isinstance(report_data, dict):
        total = report_data.get("total")
        passed = report_data.get("passed")
        failed = report_data.get("failed")
        failures = report_data.get("failures")
        if isinstance(total, int) and isinstance(passed, int) and isinstance(failed, int) and isinstance(failures, list):
            if total == passed + failed and total >= 0 and passed >= 0 and failed >= 0:
                rep_valid = True
    scores["tests_validation_report_present_and_well_formed"] = 1.0 if rep_valid else 0.0

    stdout_path = workspace / "tests" / "validation_stdout.txt"
    stdout_text = _safe_read_text(stdout_path)
    scores["tests_validation_stdout_captured"] = 1.0 if (stdout_text is not None and stdout_text.strip() != "") else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()