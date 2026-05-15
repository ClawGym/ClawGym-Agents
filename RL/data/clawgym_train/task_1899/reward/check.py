import json
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import csv
import re
from urllib.parse import urlparse
from datetime import datetime


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "@" in host:
            host = host.split("@", 1)[-1]
        if ":" in host:
            host = host.split(":", 1)[0]
        return host
    except Exception:
        return None


def _domains_equal(d1: str, d2: str) -> bool:
    def norm(d: str) -> str:
        d = d.lower().strip()
        if d.startswith("www."):
            d = d[4:]
        return d
    return norm(d1) == norm(d2)


def _parse_iso8601(ts: str) -> bool:
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        datetime.fromisoformat(ts)
        return True
    except Exception:
        return False


def _compute_expected_from_csv(csv_path: Path) -> Tuple[List[Dict[str, str]], int, int]:
    issues: List[Dict[str, str]] = []
    errors = 0
    warnings = 0
    try:
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item_id = (row.get('item_id') or '').strip()
                description = (row.get('description') or '').strip()
                muzzleloader = (row.get('muzzleloader') or '').strip().lower()
                blank_powder = (row.get('blank_powder') or '').strip().lower()
                safety_cert_path = (row.get('safety_cert_path') or '').strip()

                if muzzleloader == 'yes' and blank_powder == 'yes' and safety_cert_path == '':
                    errors += 1
                    issues.append({
                        "level": "ERROR",
                        "code": "CERT_MISSING",
                        "item_id": item_id,
                        "message": "muzzleloader with blank powder requires safety_cert_path",
                    })
                if description == '':
                    warnings += 1
                    issues.append({
                        "level": "WARNING",
                        "code": "DESC_MISSING",
                        "item_id": item_id,
                        "message": "description is empty",
                    })
                if blank_powder == 'yes' and muzzleloader == 'no':
                    warnings += 1
                    issues.append({
                        "level": "WARNING",
                        "code": "BP_NO_FIREARM",
                        "item_id": item_id,
                        "message": "blank_powder is 'yes' but muzzleloader is 'no'; verify classification and storage",
                    })
    except Exception:
        return [], 0, 0
    return issues, errors, warnings


def _parse_validator_text(text: str) -> Tuple[List[Dict[str, str]], Optional[int], Optional[int]]:
    issues: List[Dict[str, str]] = []
    total_errors: Optional[int] = None
    total_warnings: Optional[int] = None
    if text is None:
        return issues, total_errors, total_warnings
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("ERROR [") or line.startswith("WARNING ["):
            m = re.match(r'^(ERROR|WARNING) \[([A-Z0-9_]+)\] (.+)$', line)
            if not m:
                continue
            level = m.group(1)
            rest = m.group(3)
            item_match = re.search(r'item_id=([A-Za-z0-9_-]+)', rest)
            item_id = item_match.group(1) if item_match else ""
            msg = ""
            if " - " in rest:
                msg = rest.split(" - ", 1)[1].strip()
            issues.append({
                "level": level,
                "code": m.group(2),
                "item_id": item_id,
                "message": msg
            })
        elif line.startswith("SUMMARY"):
            m2 = re.search(r'errors=(\d+)\s+warnings=(\d+)', line)
            if m2:
                total_errors = int(m2.group(1))
                total_warnings = int(m2.group(2))
    return issues, total_errors, total_warnings


def _load_inventory_report(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[int], Optional[int]]:
    data = _safe_load_json(path)
    if data is None:
        return None, None, None
    if isinstance(data, dict):
        issues = data.get("issues")
        summary = data.get("summary") or {}
        if not isinstance(issues, list):
            return None, None, None
        te = summary.get("total_errors")
        tw = summary.get("total_warnings")
        if not isinstance(te, int) or not isinstance(tw, int):
            return None, None, None
        for it in issues:
            if not isinstance(it, dict):
                return None, None, None
            for k in ("item_id", "level", "code", "message"):
                if k not in it:
                    return None, None, None
        return issues, te, tw
    return None, None, None


def _parse_research_entries(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = _safe_load_json(path)
    if data is None:
        return None
    entries: Optional[List[Dict[str, Any]]] = None
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        maybe = data.get("queries") or data.get("searches")
        if isinstance(maybe, list):
            entries = maybe
    if entries is None:
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        if not isinstance(entry.get("query"), str) or not entry.get("query").strip():
            return None
        if not isinstance(entry.get("search_engine"), str) or not entry.get("search_engine").strip():
            return None
        ts = entry.get("timestamp")
        if not isinstance(ts, str) or not _parse_iso8601(ts):
            return None
        resources = entry.get("resources")
        if not isinstance(resources, list) or len(resources) < 3:
            return None
        seen_urls = set()
        for res in resources:
            if not isinstance(res, dict):
                return None
            title = res.get("title")
            url = res.get("url")
            domain = res.get("domain")
            if not isinstance(title, str) or not title.strip():
                return None
            if not isinstance(url, str) or not url.strip():
                return None
            if url in seen_urls:
                return None
            seen_urls.add(url)
            if not isinstance(domain, str) or not domain.strip():
                return None
            url_dom = _domain_from_url(url) or ""
            if not url_dom:
                return None
            if not _domains_equal(domain, url_dom):
                return None
    return entries


def _extract_urls_from_text(text: str) -> List[str]:
    if not text:
        return []
    urls = re.findall(r'https?://[^\s<>\]\)"]+', text)
    cleaned = [u.rstrip('.,;!?)"]') for u in urls]
    unique = []
    seen = set()
    for u in cleaned:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def _find_subject_line(text: str) -> Optional[str]:
    if not text:
        return None
    for line in text.splitlines():
        if re.match(r'^\s*Subject\s*:\s*.+$', line, flags=re.IGNORECASE):
            return line.strip()
    return None


def _extract_counts_from_text(text: str) -> Tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    err = None
    warn = None
    m1 = re.search(r'errors?\s*[:=]\s*(\d+)', text, flags=re.IGNORECASE)
    if m1:
        err = int(m1.group(1))
    m2 = re.search(r'warnings?\s*[:=]\s*(\d+)', text, flags=re.IGNORECASE)
    if m2:
        warn = int(m2.group(1))
    if err is None:
        m3 = re.search(r'(\d+)\s+errors?\b', text, flags=re.IGNORECASE)
        if m3:
            err = int(m3.group(1))
    if warn is None:
        m4 = re.search(r'(\d+)\s+warnings?\b', text, flags=re.IGNORECASE)
        if m4:
            warn = int(m4.group(1))
    return err, warn


def _email_contains_issue_bullets(text: str, expected_issues: List[Dict[str, str]]) -> bool:
    if not text:
        return False
    bullet_lines = []
    for line in text.splitlines():
        if re.match(r'^\s*[-*\u2022]\s+', line):
            bullet_lines.append(line.strip())
    if not bullet_lines:
        return False
    for exp in expected_issues:
        item_id = exp["item_id"]
        code = exp["code"]
        found = any((item_id in bl and code in bl) for bl in bullet_lines)
        if not found:
            return False
    return True


def _urls_from_research(entries: List[Dict[str, Any]]) -> Tuple[set, set]:
    urls = set()
    gov_urls = set()
    for entry in entries:
        for res in entry.get("resources", []):
            u = res.get("url")
            d = res.get("domain", "")
            if isinstance(u, str):
                urls.add(u)
                if isinstance(d, str) and d.lower().endswith(".gov"):
                    gov_urls.add(u)
    return urls, gov_urls


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "validation_raw_output_exists": 0.0,
        "validation_raw_output_matches_expected": 0.0,
        "validation_report_structure": 0.0,
        "validation_report_matches_expected": 0.0,
        "research_structure_and_counts": 0.0,
        "research_contains_gov_resource": 0.0,
        "park_email_subject_present": 0.0,
        "park_email_counts_and_bullets": 0.0,
        "park_email_links_valid_and_gov_included": 0.0,
        "park_email_requests_confirmation": 0.0,
        "veteran_email_subject_present": 0.0,
        "veteran_email_counts_and_bullets": 0.0,
        "veteran_email_links_valid": 0.0,
    }

    csv_path = workspace / "input" / "gear_inventory.csv"
    expected_issues, expected_errors, expected_warnings = _compute_expected_from_csv(csv_path)

    raw_output_path = workspace / "output" / "validation" / "raw_output.txt"
    report_path = workspace / "output" / "validation" / "inventory_validation_report.json"
    research_path = workspace / "output" / "research" / "safety_guidelines_search.json"
    park_email_path = workspace / "output" / "emails" / "park_permit_draft.txt"
    vet_email_path = workspace / "output" / "emails" / "veteran_friend_draft.txt"

    raw_text = _safe_read_text(raw_output_path)
    if raw_text is not None:
        scores["validation_raw_output_exists"] = 1.0
        parsed_issues, parsed_errs, parsed_warns = _parse_validator_text(raw_text)
        ok_counts = (parsed_errs == expected_errors and parsed_warns == expected_warnings)
        exp_set = {(i["item_id"], i["code"], i["level"]) for i in expected_issues}
        got_set = {(i["item_id"], i["code"], i["level"]) for i in parsed_issues}
        ok_issues = exp_set.issubset(got_set) and len(exp_set) > 0
        if ok_counts and ok_issues:
            scores["validation_raw_output_matches_expected"] = 1.0
    else:
        scores["validation_raw_output_exists"] = 0.0
        scores["validation_raw_output_matches_expected"] = 0.0

    issues_list, total_errors, total_warnings = _load_inventory_report(report_path)
    if issues_list is not None and total_errors is not None and total_warnings is not None:
        scores["validation_report_structure"] = 1.0
        exp_set = {(i["item_id"], i["code"], i["level"]) for i in expected_issues}
        got_set = {(i.get("item_id", ""), i.get("code", ""), i.get("level", "")) for i in issues_list}
        ok_totals = (total_errors == expected_errors and total_warnings == expected_warnings)
        ok_match = (exp_set == got_set and len(exp_set) > 0)
        if ok_totals and ok_match:
            scores["validation_report_matches_expected"] = 1.0

    research_entries = _parse_research_entries(research_path) if research_path.exists() else None
    if research_entries is not None:
        if len(research_entries) >= 2:
            scores["research_structure_and_counts"] = 1.0
        contains_gov = False
        for entry in research_entries:
            for res in entry.get("resources", []):
                dom = res.get("domain", "").lower() if isinstance(res.get("domain"), str) else ""
                if dom.endswith(".gov"):
                    contains_gov = True
                    break
            if contains_gov:
                break
        if contains_gov:
            scores["research_contains_gov_resource"] = 1.0

    expected_pairs = [{"item_id": i["item_id"], "code": i["code"]} for i in expected_issues]
    research_urls = set()
    gov_urls = set()
    if research_entries is not None:
        research_urls, gov_urls = _urls_from_research(research_entries)

    park_text = _safe_read_text(park_email_path) or ""
    if park_text:
        if _find_subject_line(park_text) is not None:
            scores["park_email_subject_present"] = 1.0
        err_ct, warn_ct = _extract_counts_from_text(park_text)
        counts_ok = (err_ct == expected_errors and warn_ct == expected_warnings)
        bullets_ok = _email_contains_issue_bullets(park_text, expected_pairs)
        if counts_ok and bullets_ok:
            scores["park_email_counts_and_bullets"] = 1.0
        park_urls = _extract_urls_from_text(park_text)
        park_urls_from_research = [u for u in park_urls if u in research_urls]
        links_count_ok = 1 <= len(park_urls_from_research) <= 2
        has_gov_link = any(u in gov_urls for u in park_urls_from_research)
        if links_count_ok and has_gov_link:
            scores["park_email_links_valid_and_gov_included"] = 1.0
        if re.search(r'\bconfirm\b', park_text, flags=re.IGNORECASE):
            scores["park_email_requests_confirmation"] = 1.0

    vet_text = _safe_read_text(vet_email_path) or ""
    if vet_text:
        if _find_subject_line(vet_text) is not None:
            scores["veteran_email_subject_present"] = 1.0
        err_ct_v, warn_ct_v = _extract_counts_from_text(vet_text)
        counts_ok_v = (err_ct_v == expected_errors and warn_ct_v == expected_warnings)
        bullets_ok_v = _email_contains_issue_bullets(vet_text, expected_pairs)
        if counts_ok_v and bullets_ok_v:
            scores["veteran_email_counts_and_bullets"] = 1.0
        vet_urls = _extract_urls_from_text(vet_text)
        vet_urls_from_research = [u for u in vet_urls if u in research_urls]
        links_count_ok_v = 1 <= len(vet_urls_from_research) <= 2
        if links_count_ok_v:
            scores["veteran_email_links_valid"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()