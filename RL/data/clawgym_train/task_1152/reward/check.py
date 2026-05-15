import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            headers = set(reader.fieldnames or [])
        required = {"date", "item", "details", "location"}
        if not required.issubset(headers):
            return None
        return rows
    except Exception:
        return None


def safe_parse_simple_yaml(path: Path) -> Optional[Dict[str, object]]:
    text = safe_read_text(path)
    if text is None:
        return None
    data: Dict[str, object] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if re.fullmatch(r"-?\d+", val):
            try:
                data[key] = int(val)
                continue
            except Exception:
                pass
        data[key] = val
    return data


def normalize_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^0-9a-z]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_announcements_md(path: Path) -> Optional[Dict[str, List[str]]]:
    text = safe_read_text(path)
    if text is None:
        return None
    urgent: List[str] = []
    notice: List[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*-\s*\[(urgent|notice)\]\s*(.+?)\s*$", line, flags=re.IGNORECASE)
        if m:
            tag = m.group(1).lower()
            content = m.group(2).strip()
            if tag == "urgent":
                urgent.append(content)
            elif tag == "notice":
                notice.append(content)
    return {"urgent": urgent, "notice": notice}


def extract_subject_from_email(text: str) -> Optional[str]:
    for line in text.splitlines():
        if re.match(r"^\s*subject\s*:", line, flags=re.IGNORECASE):
            _, val = line.split(":", 1)
            return val.strip()
    return None


def subject_begins_with_prefix(email_text: str, prefix: str) -> bool:
    subj = extract_subject_from_email(email_text)
    if subj is not None:
        return subj.startswith(prefix)
    for line in email_text.splitlines():
        if line.strip().startswith(prefix):
            return True
    return False


def cron_line_tokens(line: str) -> Optional[Tuple[int, int, str, str, str, str]]:
    if not line or line.strip().startswith("#"):
        return None
    parts = re.split(r"\s+", line.strip(), maxsplit=5)
    if len(parts) < 6:
        return None
    min_s, hour_s, dom, month, dow, cmd = parts
    if not re.fullmatch(r"\d{1,2}", min_s) or not re.fullmatch(r"\d{1,2}", hour_s):
        return None
    try:
        minute = int(min_s, 10)
        hour = int(hour_s, 10)
    except Exception:
        return None
    return (minute, hour, dom, month, dow, cmd)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    date_str = "2026-04-20"
    script_path = workspace / "scripts" / "daily_summary.py"
    report_path = workspace / "output" / "reports" / f"{date_str}_kabukicho_summary.txt"
    log_path = workspace / "output" / "logs" / f"run_{date_str}.log"
    cron_path = workspace / "output" / "scheduler" / "cron.tab"
    manager_email_path = workspace / "output" / "emails" / f"{date_str}_manager_email.txt"
    neighbors_email_path = workspace / "output" / "emails" / f"{date_str}_neighbors_email.txt"

    schedule_path = workspace / "input" / "schedule.csv"
    announcements_path = workspace / "input" / "announcements.md"
    contacts_path = workspace / "input" / "contacts.json"
    prefs_path = workspace / "input" / "preferences.yaml"

    scores = {
        "script_file_exists": 0.0,
        "cron_config_exists": 0.0,
        "cron_runs_at_preferences_time": 0.0,
        "cron_references_script": 0.0,
        "test_log_exists": 0.0,
        "log_contains_error_missing_pickup": 0.0,
        "report_file_exists": 0.0,
        "report_contains_date": 0.0,
        "report_contains_neighborhood": 0.0,
        "report_includes_all_events": 0.0,
        "report_includes_urgent_announcements": 0.0,
        "report_includes_notice_announcements": 0.0,
        "manager_email_exists": 0.0,
        "manager_email_has_subject_prefix": 0.0,
        "manager_email_mentions_missing_pickup_for_date": 0.0,
        "manager_email_quotes_error_lines": 0.0,
        "manager_email_includes_urgent_announcements": 0.0,
        "manager_email_addresses_manager": 0.0,
        "neighbors_email_exists": 0.0,
        "neighbors_email_has_subject_prefix": 0.0,
        "neighbors_email_addresses_neighbors": 0.0,
        "neighbors_email_includes_all_events": 0.0,
        "neighbors_email_includes_notice_announcements": 0.0,
        "neighbors_email_includes_urgent_announcements": 0.0,
    }

    if script_path.is_file():
        scores["script_file_exists"] = 1.0

    schedule_rows = safe_parse_csv(schedule_path)
    announcements = extract_announcements_md(announcements_path)
    contacts = safe_load_json(contacts_path)
    prefs = safe_parse_simple_yaml(prefs_path)

    expected_events: List[Dict[str, str]] = []
    if schedule_rows is not None:
        for r in schedule_rows:
            if (r.get("date") or "").strip() == date_str:
                expected_events.append(r)

    urgent_texts: List[str] = announcements["urgent"] if announcements else []
    notice_texts: List[str] = announcements["notice"] if announcements else []

    subject_prefix = ""
    daily_time = None
    neighborhood = None
    if prefs is not None:
        subject_prefix = str(prefs.get("email_subject_prefix", "") or "")
        daily_time = str(prefs.get("daily_time", "") or "")
        neighborhood = str(prefs.get("neighborhood", "") or "")

    manager_email = None
    manager_name = None
    neighbors_list: List[str] = []
    if contacts is not None:
        be = contacts.get("building_manager") or {}
        manager_email = be.get("email")
        manager_name = be.get("name")
        neighbors_list = contacts.get("neighbors_list") or []

    if cron_path.is_file():
        scores["cron_config_exists"] = 1.0
        cron_text = safe_read_text(cron_path) or ""
        minute_expected = None
        hour_expected = None
        if daily_time and re.fullmatch(r"\d{2}:\d{2}", daily_time.strip()):
            hour_expected = int(daily_time[:2])
            minute_expected = int(daily_time[3:])
        has_time_match = False
        has_script_ref = False
        for line in cron_text.splitlines():
            tokens = cron_line_tokens(line)
            if tokens is None:
                continue
            minute, hour, _dom, _month, _dow, cmd = tokens
            if "scripts/daily_summary.py" in cmd:
                has_script_ref = True
            if minute_expected is not None and hour_expected is not None:
                if minute == minute_expected and hour == hour_expected and "scripts/daily_summary.py" in cmd:
                    has_time_match = True
        if minute_expected is not None and hour_expected is not None and has_time_match:
            scores["cron_runs_at_preferences_time"] = 1.0
        if has_script_ref:
            scores["cron_references_script"] = 1.0

    log_text = None
    if log_path.is_file():
        scores["test_log_exists"] = 1.0
        log_text = safe_read_text(log_path) or ""
        found_error = False
        for line in (log_text.splitlines() if log_text else []):
            if line.startswith("ERROR:") and re.search(r"missing\s+pickup\s+for\s+" + re.escape(date_str), line, flags=re.IGNORECASE):
                found_error = True
                break
        if found_error:
            scores["log_contains_error_missing_pickup"] = 1.0

    report_text = None
    if report_path.is_file():
        scores["report_file_exists"] = 1.0
        report_text = safe_read_text(report_path) or ""

        if date_str in (report_text or ""):
            scores["report_contains_date"] = 1.0
        if neighborhood and neighborhood in (report_text or ""):
            scores["report_contains_neighborhood"] = 1.0

        if expected_events:
            all_present = True
            for ev in expected_events:
                item = (ev.get("item") or "").strip()
                if item and item not in (report_text or ""):
                    all_present = False
                    break
            if all_present:
                scores["report_includes_all_events"] = 1.0

        if urgent_texts:
            all_urgent_present = True
            norm_report = normalize_text(report_text or "")
            for u in urgent_texts:
                if normalize_text(u) not in norm_report:
                    all_urgent_present = False
                    break
            if all_urgent_present:
                scores["report_includes_urgent_announcements"] = 1.0

        if notice_texts:
            all_notice_present = True
            norm_report = normalize_text(report_text or "")
            for n in notice_texts:
                if normalize_text(n) not in norm_report:
                    all_notice_present = False
                    break
            if all_notice_present:
                scores["report_includes_notice_announcements"] = 1.0

    manager_email_text = None
    if manager_email_path.is_file():
        scores["manager_email_exists"] = 1.0
        manager_email_text = safe_read_text(manager_email_path) or ""

        if subject_prefix and subject_begins_with_prefix(manager_email_text, subject_prefix):
            scores["manager_email_has_subject_prefix"] = 1.0

        if re.search(r"missing\s+pickup.*" + re.escape(date_str), manager_email_text, flags=re.IGNORECASE):
            scores["manager_email_mentions_missing_pickup_for_date"] = 1.0

        if log_text:
            error_lines = [ln for ln in log_text.splitlines() if ln.startswith("ERROR:")]
            if error_lines:
                quoted_all = True
                for el in error_lines:
                    if el not in manager_email_text:
                        quoted_all = False
                        break
                if quoted_all:
                    scores["manager_email_quotes_error_lines"] = 1.0

        if urgent_texts:
            all_urgent_present_mgr = True
            norm_mgr = normalize_text(manager_email_text or "")
            for u in urgent_texts:
                if normalize_text(u) not in norm_mgr:
                    all_urgent_present_mgr = False
                    break
            if all_urgent_present_mgr:
                scores["manager_email_includes_urgent_announcements"] = 1.0

        addr_ok = False
        if manager_email and manager_email in (manager_email_text or ""):
            addr_ok = True
        elif manager_name and manager_name in (manager_email_text or ""):
            addr_ok = True
        if addr_ok:
            scores["manager_email_addresses_manager"] = 1.0

    neighbors_email_text = None
    if neighbors_email_path.is_file():
        scores["neighbors_email_exists"] = 1.0
        neighbors_email_text = safe_read_text(neighbors_email_path) or ""

        if subject_prefix and subject_begins_with_prefix(neighbors_email_text, subject_prefix):
            scores["neighbors_email_has_subject_prefix"] = 1.0

        neighbors_ok = False
        for addr in neighbors_list:
            if addr in (neighbors_email_text or ""):
                neighbors_ok = True
                break
        if neighbors_ok:
            scores["neighbors_email_addresses_neighbors"] = 1.0

        if expected_events:
            all_present_nei = True
            for ev in expected_events:
                item = (ev.get("item") or "").strip()
                if item and item not in (neighbors_email_text or ""):
                    all_present_nei = False
                    break
            if all_present_nei:
                scores["neighbors_email_includes_all_events"] = 1.0

        if notice_texts:
            all_notice_present_nei = True
            norm_nei = normalize_text(neighbors_email_text or "")
            for n in notice_texts:
                if normalize_text(n) not in norm_nei:
                    all_notice_present_nei = False
                    break
            if all_notice_present_nei:
                scores["neighbors_email_includes_notice_announcements"] = 1.0

        if urgent_texts:
            all_urgent_present_nei = True
            norm_nei = normalize_text(neighbors_email_text or "")
            for u in urgent_texts:
                if normalize_text(u) not in norm_nei:
                    all_urgent_present_nei = False
                    break
            if all_urgent_present_nei:
                scores["neighbors_email_includes_urgent_announcements"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()