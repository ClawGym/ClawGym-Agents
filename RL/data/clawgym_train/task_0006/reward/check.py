import json
import csv
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        text = _read_text_safe(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _load_csv_dicts_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return rows
    except Exception:
        return None


def _is_iso8601(s: Any) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        # Handle trailing Z for UTC
        st = s.replace("Z", "+00:00") if s.endswith("Z") else s
        datetime.fromisoformat(st)
        return True
    except Exception:
        return False


def _parse_bool_str(s: str) -> Optional[bool]:
    if not isinstance(s, str):
        return None
    sl = s.strip().lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    return None


def _status_is_success(val: Any) -> bool:
    # Success only if 200
    try:
        if isinstance(val, int):
            return val == 200
        if isinstance(val, str):
            return val.strip() == "200"
    except Exception:
        pass
    return False


def _parse_security_txt(path: Path) -> Tuple[List[str], str, str]:
    """
    Returns: (contacts list, policy_expires string or "", acknowledgments string or "")
    """
    contacts: List[str] = []
    policy_expires: str = ""
    acknowledgments: str = ""
    content = _read_text_safe(path)
    if content is None:
        return contacts, policy_expires, acknowledgments
    for line in content.splitlines():
        ln = line.strip()
        if not ln:
            continue
        # Ignore comments that start with #
        if ln.startswith("#"):
            continue
        # Case-insensitive field matching; allow leading spaces
        if ln.lower().startswith("contact:"):
            value = ln[len("contact:"):].strip()
            contacts.append(value)
        elif ln.lower().startswith("expires:") and policy_expires == "":
            value = ln[len("expires:"):].strip()
            policy_expires = value
        elif ln.lower().startswith("acknowledgments:") and acknowledgments == "":
            value = ln[len("acknowledgments:"):].strip()
            acknowledgments = value
    return contacts, policy_expires, acknowledgments


def _count_robots_disallow(path: Path) -> int:
    text = _read_text_safe(path)
    if text is None:
        return 0
    count = 0
    for line in text.splitlines():
        ln = line.lstrip()
        if not ln:
            continue
        if ln.startswith("#"):
            continue
        if ln.lower().startswith("disallow:"):
            count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "json_report_exists_and_valid_structure": 0.0,
        "csv_report_exists_and_valid_structure": 0.0,
        "json_report_covers_all_domains": 0.0,
        "csv_report_covers_all_domains": 0.0,
        "meta_json_present_and_valid": 0.0,
        "security_txt_file_presence_matches_meta": 0.0,
        "robots_txt_file_presence_matches_meta": 0.0,
        "security_txt_parsed_fields_match_report": 0.0,
        "robots_txt_count_matches_report": 0.0,
        "risk_rating_correct": 0.0,
        "reports_json_csv_consistency": 0.0,
    }

    # Load input vendor domains
    vendor_csv_path = workspace / "input" / "vendor_domains.csv"
    vendor_rows = _load_csv_dicts_safe(vendor_csv_path)
    if not vendor_rows:
        # Cannot proceed with domain-based checks
        return scores

    # Build expected domain map
    expected_domains: Dict[str, Dict[str, Any]] = {}
    for row in vendor_rows:
        org_name = (row.get("org_name") or "").strip()
        domain = (row.get("domain") or "").strip()
        used_str = (row.get("used_by_clients") or "").strip()
        used_bool = _parse_bool_str(used_str)
        if not org_name or not domain or used_bool is None:
            # Malformed input; fail grading gracefully
            return scores
        expected_domains[domain] = {
            "org_name": org_name,
            "used_by_clients": used_bool,
        }

    # Load reports
    report_json_path = workspace / "output" / "report" / "security_posture.json"
    report_csv_path = workspace / "output" / "report" / "security_posture.csv"
    report_json = _load_json_safe(report_json_path)
    report_csv_rows = _load_csv_dicts_safe(report_csv_path)

    # Validate JSON report structure
    json_valid_structure = False
    json_records_by_domain: Dict[str, Dict[str, Any]] = {}
    required_fields = [
        "domain",
        "org_name",
        "used_by_clients",
        "security_txt_present",
        "security_txt_path",
        "contacts",
        "policy_expires",
        "acknowledgments",
        "robots_txt_present",
        "robots_disallow_count",
        "last_checked_utc",
        "risk_rating",
    ]
    allowed_security_paths = {"/.well-known/security.txt", "/security.txt"}
    if isinstance(report_json, list) and len(report_json) > 0:
        valid = True
        for rec in report_json:
            if not isinstance(rec, dict):
                valid = False
                break
            # Exact field match (no extras, no missing)
            if set(rec.keys()) != set(required_fields):
                valid = False
                break
            # Type checks
            if not isinstance(rec["domain"], str) or not rec["domain"]:
                valid = False
                break
            if not isinstance(rec["org_name"], str):
                valid = False
                break
            if not isinstance(rec["used_by_clients"], bool):
                valid = False
                break
            if not isinstance(rec["security_txt_present"], bool):
                valid = False
                break
            stp = rec["security_txt_path"]
            if stp is not None and not (isinstance(stp, str) and stp in allowed_security_paths):
                valid = False
                break
            if not isinstance(rec["contacts"], list) or any(not isinstance(c, str) for c in rec["contacts"]):
                valid = False
                break
            if not isinstance(rec["policy_expires"], str):
                valid = False
                break
            if not isinstance(rec["acknowledgments"], str):
                valid = False
                break
            if not isinstance(rec["robots_txt_present"], bool):
                valid = False
                break
            if not isinstance(rec["robots_disallow_count"], int) or rec["robots_disallow_count"] < 0:
                valid = False
                break
            if not _is_iso8601(rec["last_checked_utc"]):
                valid = False
                break
            if rec["risk_rating"] not in {"Low", "Medium", "High"}:
                valid = False
                break
            # Build map
            json_records_by_domain[rec["domain"]] = rec
        json_valid_structure = valid
    scores["json_report_exists_and_valid_structure"] = 1.0 if json_valid_structure else 0.0

    # Validate CSV report structure
    csv_valid_structure = False
    csv_rows_by_domain: Dict[str, Dict[str, str]] = {}
    required_csv_headers = [
        "domain",
        "org_name",
        "used_by_clients",
        "security_txt_present",
        "security_txt_path",
        "contacts",
        "policy_expires",
        "acknowledgments",
        "robots_txt_present",
        "robots_disallow_count",
        "last_checked_utc",
        "risk_rating",
    ]
    if isinstance(report_csv_rows, list) and report_csv_rows is not None and len(report_csv_rows) >= 0:
        # Validate headers exactly, preserving order
        try:
            with report_csv_path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                headers = next(reader, None)
        except Exception:
            headers = None
        if headers == required_csv_headers:
            valid = True
            for row in report_csv_rows:
                # Basic field presence
                if any(h not in row for h in required_csv_headers):
                    valid = False
                    break
                # Types and formats
                if not row["domain"]:
                    valid = False
                    break
                if row["used_by_clients"].strip().lower() not in {"true", "false"}:
                    valid = False
                    break
                if row["security_txt_present"].strip().lower() not in {"true", "false"}:
                    valid = False
                    break
                path_val = row["security_txt_path"].strip()
                if path_val and path_val not in allowed_security_paths:
                    valid = False
                    break
                if row["robots_txt_present"].strip().lower() not in {"true", "false"}:
                    valid = False
                    break
                try:
                    int(row["robots_disallow_count"])
                except Exception:
                    valid = False
                    break
                if not _is_iso8601(row["last_checked_utc"].strip()):
                    valid = False
                    break
                if row["risk_rating"] not in {"Low", "Medium", "High"}:
                    valid = False
                    break
                csv_rows_by_domain[row["domain"]] = row
            csv_valid_structure = valid
    scores["csv_report_exists_and_valid_structure"] = 1.0 if csv_valid_structure else 0.0

    # Coverage checks comparing to input domains
    json_covers = False
    if json_valid_structure:
        json_covers = set(json_records_by_domain.keys()) == set(expected_domains.keys())
        # Also check org_name and used_by_clients match vendor file
        if json_covers:
            for domain, expected in expected_domains.items():
                rec = json_records_by_domain.get(domain)
                if rec is None:
                    json_covers = False
                    break
                if rec["org_name"] != expected["org_name"]:
                    json_covers = False
                    break
                if rec["used_by_clients"] is not expected["used_by_clients"]:
                    json_covers = False
                    break
    scores["json_report_covers_all_domains"] = 1.0 if json_covers else 0.0

    csv_covers = False
    if csv_valid_structure:
        csv_covers = set(csv_rows_by_domain.keys()) == set(expected_domains.keys())
        if csv_covers:
            for domain, expected in expected_domains.items():
                row = csv_rows_by_domain.get(domain)
                if row is None:
                    csv_covers = False
                    break
                if (row["org_name"] or "").strip() != expected["org_name"]:
                    csv_covers = False
                    break
                used = _parse_bool_str((row["used_by_clients"] or "").strip())
                if used is None or used is not expected["used_by_clients"]:
                    csv_covers = False
                    break
    scores["csv_report_covers_all_domains"] = 1.0 if csv_covers else 0.0

    # Meta.json per domain and validity
    meta_valid_all = True
    per_domain_meta: Dict[str, Dict[str, Any]] = {}
    for domain in expected_domains.keys():
        meta_path = workspace / "output" / "downloads" / domain / "meta.json"
        meta = _load_json_safe(meta_path)
        if not isinstance(meta, dict):
            meta_valid_all = False
            break
        # Required keys
        required_meta_keys = {
            "domain",
            "attempted_paths",
            "security_txt_status",
            "robots_txt_status",
            "chosen_security_txt_path",
            "fetched_at_utc",
        }
        if set(meta.keys()) != required_meta_keys:
            meta_valid_all = False
            break
        if meta["domain"] != domain:
            meta_valid_all = False
            break
        attempted = meta.get("attempted_paths")
        if not isinstance(attempted, list) or attempted != ["/.well-known/security.txt", "/security.txt"]:
            meta_valid_all = False
            break
        sts = meta.get("security_txt_status")
        if not isinstance(sts, dict) or set(sts.keys()) != set(attempted):
            meta_valid_all = False
            break
        # robots status can be int or string or error message; accept any non-null type
        if "robots_txt_status" not in meta:
            meta_valid_all = False
            break
        chosen = meta.get("chosen_security_txt_path")
        if chosen is not None and chosen not in attempted:
            meta_valid_all = False
            break
        if not _is_iso8601(meta.get("fetched_at_utc")):
            meta_valid_all = False
            break
        per_domain_meta[domain] = meta
    scores["meta_json_present_and_valid"] = 1.0 if meta_valid_all and len(per_domain_meta) == len(expected_domains) else 0.0

    # Security.txt file presence matches meta
    sec_file_presence_ok = True
    for domain in expected_domains.keys():
        meta = per_domain_meta.get(domain)
        dir_path = workspace / "output" / "downloads" / domain
        sec_path = dir_path / "security.txt"
        if meta is None:
            sec_file_presence_ok = False
            break
        chosen = meta.get("chosen_security_txt_path")
        # If chosen path indicates success, require file; else ensure absence
        if chosen is None:
            # Should not have a placeholder security.txt
            if sec_path.exists():
                sec_file_presence_ok = False
                break
        else:
            # ensure chosen path had success status 200
            sts_map = meta.get("security_txt_status", {})
            chosen_sts = sts_map.get(chosen)
            if not _status_is_success(chosen_sts):
                sec_file_presence_ok = False
                break
            if not sec_path.exists():
                sec_file_presence_ok = False
                break
    scores["security_txt_file_presence_matches_meta"] = 1.0 if sec_file_presence_ok and meta_valid_all else 0.0

    # Robots.txt file presence matches meta
    robots_file_presence_ok = True
    for domain in expected_domains.keys():
        meta = per_domain_meta.get(domain)
        dir_path = workspace / "output" / "downloads" / domain
        robots_path = dir_path / "robots.txt"
        if meta is None:
            robots_file_presence_ok = False
            break
        robots_status = meta.get("robots_txt_status")
        success = _status_is_success(robots_status)
        if success:
            if not robots_path.exists():
                robots_file_presence_ok = False
                break
        else:
            # Should not create placeholder file
            if robots_path.exists():
                robots_file_presence_ok = False
                break
    scores["robots_txt_file_presence_matches_meta"] = 1.0 if robots_file_presence_ok and meta_valid_all else 0.0

    # Security.txt parsed fields match reports
    sec_fields_match = True
    if not (json_valid_structure and csv_valid_structure and json_covers and csv_covers):
        sec_fields_match = False
    else:
        for domain in expected_domains.keys():
            json_rec = json_records_by_domain.get(domain)
            csv_row = csv_rows_by_domain.get(domain)
            meta = per_domain_meta.get(domain)
            if json_rec is None or csv_row is None or meta is None:
                sec_fields_match = False
                break
            dir_path = workspace / "output" / "downloads" / domain
            sec_file = dir_path / "security.txt"
            chosen = meta.get("chosen_security_txt_path")
            if sec_file.exists():
                contacts, expires, acknowledgments = _parse_security_txt(sec_file)
                # JSON checks
                if json_rec["security_txt_present"] is not True:
                    sec_fields_match = False
                    break
                if json_rec["security_txt_path"] != chosen:
                    sec_fields_match = False
                    break
                if json_rec["contacts"] != contacts:
                    sec_fields_match = False
                    break
                if json_rec["policy_expires"] != expires:
                    sec_fields_match = False
                    break
                if json_rec["acknowledgments"] != acknowledgments:
                    sec_fields_match = False
                    break
                # CSV checks
                if _parse_bool_str(csv_row["security_txt_present"]) is not True:
                    sec_fields_match = False
                    break
                csv_path_val = (csv_row["security_txt_path"] or "").strip()
                exp_path = chosen if chosen is not None else ""
                if csv_path_val != (exp_path or ""):
                    sec_fields_match = False
                    break
                # Contacts semicolon-separated
                csv_contacts_field = csv_row.get("contacts", "")
                csv_contacts_items = [item.strip() for item in csv_contacts_field.split(";") if item.strip() != ""]
                if csv_contacts_items != contacts:
                    sec_fields_match = False
                    break
                if (csv_row.get("policy_expires", "") or "") != (expires or ""):
                    sec_fields_match = False
                    break
                if (csv_row.get("acknowledgments", "") or "") != (acknowledgments or ""):
                    sec_fields_match = False
                    break
            else:
                # No security.txt; JSON must reflect absence
                if json_rec["security_txt_present"] is not False:
                    sec_fields_match = False
                    break
                if json_rec["security_txt_path"] is not None:
                    sec_fields_match = False
                    break
                if _parse_bool_str(csv_row["security_txt_present"]) is not False:
                    sec_fields_match = False
                    break
                if (csv_row["security_txt_path"] or "").strip() != "":
                    sec_fields_match = False
                    break
    scores["security_txt_parsed_fields_match_report"] = 1.0 if sec_fields_match else 0.0

    # Robots.txt count matches reports
    robots_fields_match = True
    if not (json_valid_structure and csv_valid_structure and json_covers and csv_covers):
        robots_fields_match = False
    else:
        for domain in expected_domains.keys():
            json_rec = json_records_by_domain.get(domain)
            csv_row = csv_rows_by_domain.get(domain)
            meta = per_domain_meta.get(domain)
            if json_rec is None or csv_row is None or meta is None:
                robots_fields_match = False
                break
            dir_path = workspace / "output" / "downloads" / domain
            robots_file = dir_path / "robots.txt"
            robots_present = robots_file.exists()
            count = _count_robots_disallow(robots_file) if robots_present else 0
            # JSON checks
            if json_rec["robots_txt_present"] != robots_present:
                robots_fields_match = False
                break
            if json_rec["robots_disallow_count"] != count:
                robots_fields_match = False
                break
            # CSV checks
            if _parse_bool_str(csv_row["robots_txt_present"]) != robots_present:
                robots_fields_match = False
                break
            try:
                csv_count = int(csv_row["robots_disallow_count"])
            except Exception:
                robots_fields_match = False
                break
            if csv_count != count:
                robots_fields_match = False
                break
            # If absent, count should be 0
            if not robots_present and count != 0:
                robots_fields_match = False
                break
    scores["robots_txt_count_matches_report"] = 1.0 if robots_fields_match else 0.0

    # Risk rating correctness
    risk_ok = True
    if not (json_valid_structure and csv_valid_structure and json_covers and csv_covers):
        risk_ok = False
    else:
        for domain in expected_domains.keys():
            json_rec = json_records_by_domain.get(domain)
            csv_row = csv_rows_by_domain.get(domain)
            if json_rec is None or csv_row is None:
                risk_ok = False
                break
            st_present = json_rec["security_txt_present"]
            rb_present = json_rec["robots_txt_present"]
            expected_risk = "Low" if st_present else ("Medium" if rb_present else "High")
            if json_rec["risk_rating"] != expected_risk:
                risk_ok = False
                break
            if csv_row["risk_rating"] != expected_risk:
                risk_ok = False
                break
    scores["risk_rating_correct"] = 1.0 if risk_ok else 0.0

    # Cross consistency between JSON and CSV fields
    cross_ok = True
    if not (json_valid_structure and csv_valid_structure and json_covers and csv_covers):
        cross_ok = False
    else:
        for domain in expected_domains.keys():
            j = json_records_by_domain.get(domain)
            c = csv_rows_by_domain.get(domain)
            if j is None or c is None:
                cross_ok = False
                break
            # Booleans
            if _parse_bool_str(c["used_by_clients"]) is not j["used_by_clients"]:
                cross_ok = False
                break
            if _parse_bool_str(c["security_txt_present"]) is not j["security_txt_present"]:
                cross_ok = False
                break
            if _parse_bool_str(c["robots_txt_present"]) is not j["robots_txt_present"]:
                cross_ok = False
                break
            # Paths
            csv_path = (c["security_txt_path"] or "").strip()
            json_path = j["security_txt_path"] if j["security_txt_path"] is not None else ""
            if csv_path != (json_path or ""):
                cross_ok = False
                break
            # Contacts: compare lists ignoring extra spaces around items
            csv_contacts_items = [item.strip() for item in (c.get("contacts") or "").split(";") if item.strip() != ""]
            if csv_contacts_items != j["contacts"]:
                cross_ok = False
                break
            # Other fields
            if (c.get("policy_expires") or "") != (j.get("policy_expires") or ""):
                cross_ok = False
                break
            if (c.get("acknowledgments") or "") != (j.get("acknowledgments") or ""):
                cross_ok = False
                break
            try:
                if int(c["robots_disallow_count"]) != j["robots_disallow_count"]:
                    cross_ok = False
                    break
            except Exception:
                cross_ok = False
                break
            if c["risk_rating"] != j["risk_rating"]:
                cross_ok = False
                break
            # last_checked_utc: ensure both are ISO, but not forcing equality
            if not (_is_iso8601(c["last_checked_utc"]) and _is_iso8601(j["last_checked_utc"])):
                cross_ok = False
                break
    scores["reports_json_csv_consistency"] = 1.0 if cross_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()