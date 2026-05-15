import csv
import json
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def round_half_up(value: float) -> int:
    d = Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return int(d)


def parse_time_block(hhmm: str) -> Optional[str]:
    try:
        hh, mm = hhmm.split(":")
        h = int(hh)
        m = int(mm)
        total_minutes = h * 60 + m
    except Exception:
        return None
    # morning (05:00–11:59), afternoon (12:00–16:59),
    # evening (17:00–21:59), night (22:00–04:59)
    if 5 * 60 <= total_minutes <= 11 * 60 + 59:
        return "morning"
    if 12 * 60 <= total_minutes <= 16 * 60 + 59:
        return "afternoon"
    if 17 * 60 <= total_minutes <= 21 * 60 + 59:
        return "evening"
    # night includes 22:00–23:59 and 00:00–04:59
    return "night"


def weekday_full_name(date_str: str) -> Optional[str]:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A")
    except Exception:
        return None


def parse_alert_config(path: Path) -> Dict[str, object]:
    text = safe_read_text(path)
    result: Dict[str, object] = {"quiet_start": None, "quiet_end": None, "primary_recipients": []}
    if text is None:
        return result
    lines = text.splitlines()
    in_quiet = False
    in_primary = False
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if stripped.startswith("quiet_hours:"):
            in_quiet = True
            in_primary = False
            continue
        if stripped and not stripped.startswith("-") and ":" in stripped and not line.startswith(" "):
            if stripped.startswith("primary_recipients:"):
                in_primary = True
                in_quiet = False
                continue
            else:
                in_quiet = False
                in_primary = False
        if in_quiet:
            m_start = re.match(r'^\s*start:\s*["\']?([0-9]{2}:[0-9]{2})["\']?', line)
            m_end = re.match(r'^\s*end:\s*["\']?([0-9]{2}:[0-9]{2})["\']?', line)
            if m_start:
                result["quiet_start"] = m_start.group(1)
            if m_end:
                result["quiet_end"] = m_end.group(1)
        if in_primary:
            m_item = re.match(r'^\s*-\s*["\']?([A-Za-z0-9]+)["\']?', line)
            if m_item:
                result.setdefault("primary_recipients", []).append(m_item.group(1))
    return result


def detect_config_key_from_notify_py(path: Path) -> Optional[str]:
    text = safe_read_text(path)
    if text is None:
        return None
    func_match = re.search(r'def\s+select_primary_recipients\s*\(.*?\):\s*(.*?)\n\s*return\s+config\.get\(\s*[\'"]([^\'"]+)[\'"]', text, re.S)
    if func_match:
        key = func_match.group(2)
        return key
    any_match = re.search(r'return\s+config\.get\(\s*[\'"]([^\'"]+)[\'"]', text)
    if any_match:
        return any_match.group(1)
    return None


def compute_lockout_summary(inc_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, object]]]:
    buckets: Dict[Tuple[str, str], Dict[str, object]] = {}
    for r in inc_rows:
        d = r.get("date")
        t = r.get("time")
        rm = r.get("response_minutes")
        um = r.get("unlock_method")
        if d is None or t is None or rm is None or um is None:
            return None
        wk = weekday_full_name(d)
        tb = parse_time_block(t)
        try:
            rm_int = int(rm)
        except Exception:
            return None
        if wk is None or tb is None:
            return None
        key = (wk, tb)
        b = buckets.setdefault(key, {"weekday": wk, "time_block": tb, "incidents": 0, "count_keyholder": 0, "count_locksmith": 0, "count_other": 0, "sum_response": 0})
        b["incidents"] += 1
        b["sum_response"] += rm_int
        if um in ["neighbor_spare_key", "family_member", "management", "landlord"]:
            b["count_keyholder"] += 1
        elif um == "locksmith":
            b["count_locksmith"] += 1
        else:
            b["count_other"] += 1
    result = []
    for (_, _), b in buckets.items():
        inc = b["incidents"]
        avg = round_half_up(b["sum_response"] / inc) if inc > 0 else 0
        result.append({
            "weekday": b["weekday"],
            "time_block": b["time_block"],
            "incidents": inc,
            "count_keyholder": b["count_keyholder"],
            "count_locksmith": b["count_locksmith"],
            "count_other": b["count_other"],
            "avg_response_minutes": avg,
        })
    result.sort(key=lambda x: (x["weekday"], x["time_block"]))
    return result


def parse_quiet_hours(quiet_start: Optional[str], quiet_end: Optional[str]) -> Optional[Tuple[time, time]]:
    if not quiet_start or not quiet_end:
        return None
    try:
        qs = datetime.strptime(quiet_start, "%H:%M").time()
        qe = datetime.strptime(quiet_end, "%H:%M").time()
        return (qs, qe)
    except Exception:
        return None


def is_time_in_quiet_hours(hhmm: str, qs: time, qe: time) -> Optional[bool]:
    try:
        tt = datetime.strptime(hhmm, "%H:%M").time()
    except Exception:
        return None
    if qs <= qe:
        return qs <= tt <= qe
    else:
        return tt >= qs or tt <= qe


def compute_top_timeblocks_and_weekdays(summary_rows: List[Dict[str, object]]) -> Tuple[List[str], List[str]]:
    tb_counts: Dict[str, int] = {}
    wk_counts: Dict[str, int] = {}
    for r in summary_rows:
        tb_counts[r["time_block"]] = tb_counts.get(r["time_block"], 0) + int(r["incidents"])
        wk_counts[r["weekday"]] = wk_counts.get(r["weekday"], 0) + int(r["incidents"])
    max_tb = max(tb_counts.values()) if tb_counts else 0
    max_wk = max(wk_counts.values()) if wk_counts else 0
    top_tbs = sorted([k for k, v in tb_counts.items() if v == max_tb])
    top_wks = sorted([k for k, v in wk_counts.items() if v == max_wk])
    return top_tbs, top_wks


def csv_rows_equal(expected: List[Dict[str, object]], actual_rows: List[Dict[str, str]], columns: List[str]) -> bool:
    try:
        def normalize(row: Dict[str, object]) -> Tuple:
            return tuple(str(row[c]) for c in columns)
        def normalize_actual(row: Dict[str, str]) -> Tuple:
            return tuple(row.get(c, "") for c in columns)
        exp_set = sorted([normalize(r) for r in expected])
        act_set = sorted([normalize_actual(r) for r in actual_rows])
        return exp_set == act_set
    except Exception:
        return False


def section_content(text: str, heading: str, headings: List[str]) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip().lower() == heading.lower():
            start_idx = i
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    lower_headings = [h.lower() for h in headings]
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip().lower() in lower_headings:
            end_idx = j
            break
    return "\n".join(lines[start_idx + 1:end_idx])


def count_bullets(text: str) -> int:
    count = 0
    for ln in text.splitlines():
        stripped = ln.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            count += 1
    return count


def neighbors_from_contacts(contacts_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [r for r in contacts_rows if r.get("relationship", "").strip().lower() == "neighbor"]


def line_contains_all_tokens(line: str, tokens: List[str]) -> bool:
    return all(tok in line for tok in tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "lockout_summary_file_exists": 0.0,
        "lockout_summary_columns_correct": 0.0,
        "lockout_summary_values_correct": 0.0,
        "mismatched_recipients_file_exists": 0.0,
        "mismatched_recipients_columns_correct": 0.0,
        "mismatched_recipients_values_correct": 0.0,
        "meeting_notes_has_sections": 0.0,
        "meeting_notes_summary_covers_totals_and_modes": 0.0,
        "meeting_notes_findings_has_min_bullets_and_key_points": 0.0,
        "meeting_notes_action_items_min_and_owners": 0.0,
        "meeting_notes_references_complete": 0.0,
        "email_subject_correct": 0.0,
        "email_neighbors_list_includes_all": 0.0,
        "email_mentions_quiet_hours": 0.0,
    }

    inc_path = workspace / "input" / "incidents.csv"
    contacts_path = workspace / "input" / "contacts.csv"
    config_path = workspace / "input" / "alert_config.yaml"
    notify_path = workspace / "notify.py"

    out_lockout = workspace / "outputs" / "lockout_summary.csv"
    out_mismatch = workspace / "outputs" / "mismatched_recipients.csv"
    out_notes = workspace / "outputs" / "meeting_notes.md"
    out_email = workspace / "outputs" / "email_to_neighbors.txt"

    inc_header, inc_rows = safe_load_csv(inc_path)
    contacts_header, contacts_rows = safe_load_csv(contacts_path)
    config = parse_alert_config(config_path)
    notify_key = detect_config_key_from_notify_py(notify_path)

    expected_summary = None
    if inc_rows is not None:
        expected_summary = compute_lockout_summary(inc_rows)

    if out_lockout.exists():
        scores["lockout_summary_file_exists"] = 1.0
        out_header, out_rows = safe_load_csv(out_lockout)
        expected_columns = ["weekday", "time_block", "incidents", "count_keyholder", "count_locksmith", "count_other", "avg_response_minutes"]
        if out_header == expected_columns:
            scores["lockout_summary_columns_correct"] = 1.0
        else:
            scores["lockout_summary_columns_correct"] = 0.0
        if expected_summary is not None and out_rows is not None and out_header == expected_columns:
            if csv_rows_equal(expected_summary, out_rows, expected_columns):
                scores["lockout_summary_values_correct"] = 1.0
    else:
        scores["lockout_summary_file_exists"] = 0.0
        scores["lockout_summary_columns_correct"] = 0.0
        scores["lockout_summary_values_correct"] = 0.0

    expected_mismatch = None
    if contacts_rows is not None and notify_key is not None:
        contact_ids_set = {r.get("contact_id") for r in contacts_rows if r.get("contact_id") is not None}
        recipients = []
        if notify_key == "primary_recipients":
            recipients = list(config.get("primary_recipients", [])) if isinstance(config.get("primary_recipients"), list) else []
        else:
            recipients = []
            text = safe_read_text(config_path)
            if text:
                pat = rf'^{notify_key}:\s*$'
                lines = text.splitlines()
                in_key = False
                for ln in lines:
                    if re.match(pat, ln.strip()):
                        in_key = True
                        continue
                    if in_key:
                        if ln.strip().startswith("-"):
                            m = re.match(r'^\s*-\s*["\']?([A-Za-z0-9]+)["\']?', ln)
                            if m:
                                recipients.append(m.group(1))
                        elif ln.strip() and not ln.startswith(" "):
                            break
        expected_mismatch = []
        for cid in recipients:
            exists = cid in contact_ids_set
            detail = "not found in contacts.csv"
            if exists:
                rel = None
                for r in contacts_rows:
                    if r.get("contact_id") == cid:
                        rel = r.get("relationship", "")
                        break
                detail = rel if rel is not None else ""
            expected_mismatch.append({
                "contact_id": cid,
                "in_config_key": notify_key,
                "exists_in_contacts": "yes" if exists else "no",
                "detail": detail,
            })

    expected_mismatch_columns = ["contact_id", "in_config_key", "exists_in_contacts", "detail"]
    if out_mismatch.exists():
        scores["mismatched_recipients_file_exists"] = 1.0
        out_header, out_rows = safe_load_csv(out_mismatch)
        if out_header == expected_mismatch_columns:
            scores["mismatched_recipients_columns_correct"] = 1.0
        else:
            scores["mismatched_recipients_columns_correct"] = 0.0
        if expected_mismatch is not None and out_rows is not None and out_header == expected_mismatch_columns:
            exp = sorted([(r["contact_id"], r["in_config_key"], r["exists_in_contacts"], r["detail"]) for r in expected_mismatch])
            act = sorted([(r.get("contact_id", ""), r.get("in_config_key", ""), r.get("exists_in_contacts", ""), r.get("detail", "")) for r in out_rows])
            if exp == act:
                scores["mismatched_recipients_values_correct"] = 1.0
    else:
        scores["mismatched_recipients_file_exists"] = 0.0
        scores["mismatched_recipients_columns_correct"] = 0.0
        scores["mismatched_recipients_values_correct"] = 0.0

    notes_text = safe_read_text(out_notes) if out_notes.exists() else None
    headings = ["Summary:", "Findings:", "Action Items:", "References:"]
    if notes_text is not None:
        has_all = all(h in [ln.strip() for ln in notes_text.splitlines()] for h in headings)
        scores["meeting_notes_has_sections"] = 1.0 if has_all else 0.0

        summary_content = section_content(notes_text, "Summary:", headings)
        ok_summary = False
        if summary_content is not None and inc_rows is not None and expected_summary is not None:
            total_incidents = len(inc_rows)
            mentions_total = (str(total_incidents) in summary_content) and ("incident" in summary_content.lower())
            top_tbs, top_wks = compute_top_timeblocks_and_weekdays(expected_summary)
            mentions_tb = any(tb in summary_content.lower() for tb in ["morning", "afternoon", "evening", "night"] if tb in top_tbs)
            mentions_wk = any(wk.lower() in summary_content.lower() for wk in top_wks)
            ok_summary = bool(mentions_total and mentions_tb and mentions_wk)
        scores["meeting_notes_summary_covers_totals_and_modes"] = 1.0 if ok_summary else 0.0

        findings_content = section_content(notes_text, "Findings:", headings)
        ok_findings = False
        if findings_content is not None:
            bullets_count = count_bullets(findings_content)
            mentions_quiet_phrase = ("quiet" in findings_content.lower() and "hour" in findings_content.lower())
            helper_ok = False
            if inc_rows is not None and contacts_rows is not None:
                by_id = {r.get("contact_id"): r for r in contacts_rows}
                rel_counts: Dict[str, int] = {}
                for r in inc_rows:
                    cid = r.get("who_helped")
                    info = by_id.get(cid)
                    if info:
                        rel = info.get("relationship", "").lower()
                        rel_counts[rel] = rel_counts.get(rel, 0) + 1
                if rel_counts:
                    top_rel = sorted([(v, k) for k, v in rel_counts.items()], reverse=True)[0][1]
                    helper_ok = (top_rel in findings_content.lower())
            ok_findings = bullets_count >= 3 and mentions_quiet_phrase and helper_ok
        scores["meeting_notes_findings_has_min_bullets_and_key_points"] = 1.0 if ok_findings else 0.0

        action_content = section_content(notes_text, "Action Items:", headings)
        ok_actions = False
        if action_content is not None:
            bullets_count = count_bullets(action_content)
            owners_ok = False
            contact_ids = set()
            if contacts_rows is not None:
                for r in contacts_rows:
                    cid = r.get("contact_id")
                    if cid:
                        contact_ids.add(cid)
            lines = [ln.strip() for ln in action_content.splitlines() if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
            if lines:
                owners_ok = all(any(cid in ln for cid in contact_ids) or ("TBD" in ln) for ln in lines)
            ok_actions = bullets_count >= 4 and owners_ok
        scores["meeting_notes_action_items_min_and_owners"] = 1.0 if ok_actions else 0.0

        ref_content = section_content(notes_text, "References:", headings)
        if ref_content is not None:
            refs_ok = all(token in ref_content for token in ["input/incidents.csv", "input/contacts.csv", "input/alert_config.yaml", "notify.py", "outputs/mismatched_recipients.csv"])
            scores["meeting_notes_references_complete"] = 1.0 if refs_ok else 0.0
        else:
            scores["meeting_notes_references_complete"] = 0.0
    else:
        scores["meeting_notes_has_sections"] = 0.0
        scores["meeting_notes_summary_covers_totals_and_modes"] = 0.0
        scores["meeting_notes_findings_has_min_bullets_and_key_points"] = 0.0
        scores["meeting_notes_action_items_min_and_owners"] = 0.0
        scores["meeting_notes_references_complete"] = 0.0

    email_text = safe_read_text(out_email) if out_email.exists() else None
    if email_text is not None:
        lines = [ln.strip() for ln in email_text.splitlines()]
        first_nonempty = None
        for ln in lines:
            if ln:
                first_nonempty = ln
                break
        subj_ok = False
        if first_nonempty is not None:
            target = "Please confirm your spare key details"
            subj_ok = (first_nonempty == target) or (first_nonempty == f"Subject: {target}")
        scores["email_subject_correct"] = 1.0 if subj_ok else 0.0

        neighbors = neighbors_from_contacts(contacts_rows) if contacts_rows is not None else []
        neighbors_ok = False
        if neighbors:
            all_found = True
            for n in neighbors:
                tokens = [n.get("name", ""), n.get("phone", ""), n.get("availability", "")]
                found_line = any(line_contains_all_tokens(ln, tokens) for ln in lines)
                if not found_line:
                    all_found = False
                    break
            neighbors_ok = all_found
        scores["email_neighbors_list_includes_all"] = 1.0 if neighbors_ok else 0.0

        quiet_ok = False
        qs = config.get("quiet_start")
        qe = config.get("quiet_end")
        if qs and qe:
            quiet_ok = (qs in email_text and qe in email_text)
        scores["email_mentions_quiet_hours"] = 1.0 if quiet_ok else 0.0
    else:
        scores["email_subject_correct"] = 0.0
        scores["email_neighbors_list_includes_all"] = 0.0
        scores["email_mentions_quiet_hours"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()