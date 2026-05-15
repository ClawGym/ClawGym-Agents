import json
import csv
import sys
from datetime import datetime
from pathlib import Path
from collections import Counter
from typing import List, Dict, Optional, Tuple


def _read_csv_dicts(path: Path, required_fields: Optional[List[str]] = None) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if required_fields:
                header = reader.fieldnames or []
                for rf in required_fields:
                    if rf not in header:
                        return None
            return rows
    except Exception:
        return None


def _parse_dt(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open(encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return None


def _list_dir_files(path: Path) -> Optional[List[str]]:
    try:
        if not path.exists() or not path.is_dir():
            return None
        return sorted([p.name for p in path.iterdir() if p.is_file()])
    except Exception:
        return None


def _compute_expected_conflicts(team_rows: List[Dict[str, str]], family_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    expected = []
    for t in team_rows:
        t_start = _parse_dt(t.get("start", ""))
        t_end = _parse_dt(t.get("end", ""))
        if t_start is None or t_end is None:
            return None
        t_type = t.get("event_type", "")
        for f in family_rows:
            f_start = _parse_dt(f.get("start", ""))
            f_end = _parse_dt(f.get("end", ""))
            if f_start is None or f_end is None:
                return None
            # compute overlap > 0 minutes
            latest_start = max(t_start, f_start)
            earliest_end = min(t_end, f_end)
            overlap_seconds = (earliest_end - latest_start).total_seconds()
            if overlap_seconds > 0:
                overlap_minutes = int(overlap_seconds // 60)
                row = {
                    "team_event_date": _fmt_date(t_start),
                    "team_event_start": _fmt_dt(t_start),
                    "team_event_end": _fmt_dt(t_end),
                    "event_type": t_type,
                    "family_event_title": f.get("title", ""),
                    "family_event_start": _fmt_dt(f_start),
                    "family_event_end": _fmt_dt(f_end),
                    "overlap_minutes": str(overlap_minutes),
                }
                expected.append(row)
    return expected


def _compute_expected_attendance(team_rows: List[Dict[str, str]], family_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, object]]]:
    # Build conflict titles per team event
    conflicts = {}
    for t in team_rows:
        t_start = _parse_dt(t.get("start", ""))
        t_end = _parse_dt(t.get("end", ""))
        if t_start is None or t_end is None:
            return None
        t_key = (_fmt_dt(t_start), _fmt_dt(t_end), t.get("event_type", ""))
        titles = []
        for f in family_rows:
            f_start = _parse_dt(f.get("start", ""))
            f_end = _parse_dt(f.get("end", ""))
            if f_start is None or f_end is None:
                return None
            latest_start = max(t_start, f_start)
            earliest_end = min(t_end, f_end)
            if (earliest_end - latest_start).total_seconds() > 0:
                titles.append(f.get("title", ""))
        conflicts[t_key] = titles

    expected = []
    for t in team_rows:
        t_start = _parse_dt(t.get("start", ""))
        t_end = _parse_dt(t.get("end", ""))
        if t_start is None or t_end is None:
            return None
        start_str = _fmt_dt(t_start)
        end_str = _fmt_dt(t_end)
        etype = t.get("event_type", "")
        t_key = (start_str, end_str, etype)
        titles = conflicts.get(t_key, [])
        attendance_required = (t.get("attendance_required", "") or "").strip()
        if attendance_required not in ("Yes", "No"):
            return None
        if attendance_required == "Yes":
            plan = "Needs Excuse" if titles else "Attend"
        else:
            plan = "Skip (Optional)" if titles else "Attend (Optional)"
        obj = {
            "date": _fmt_date(t_start),
            "start": start_str,
            "end": end_str,
            "event_type": etype,
            "attendance_required": attendance_required,
            "plan": plan,
            "conflict_titles": titles,
        }
        expected.append(obj)
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "conflicts_header_correct": 0.0,
        "conflicts_row_count_correct": 0.0,
        "conflicts_rows_match": 0.0,
        "attendance_json_parseable": 0.0,
        "attendance_count_correct": 0.0,
        "attendance_values_correct": 0.0,
        "email_greeting_correct": 0.0,
        "email_includes_names": 0.0,
        "email_lists_excuse_events": 0.0,
        "email_forms_status_mentioned": 0.0,
        "email_closes_with_name": 0.0,
        "email_no_attachment_claim": 0.0,
    }

    # Load inputs
    team_path = workspace / "input" / "team_schedule.csv"
    family_path = workspace / "input" / "family_calendar.csv"
    contacts_path = workspace / "input" / "contacts.json"
    required_docs_path = workspace / "input" / "required_documents.txt"
    forms_dir = workspace / "input" / "forms"

    team_rows = _read_csv_dicts(team_path, required_fields=["start", "end", "event_type", "attendance_required"])
    family_rows = _read_csv_dicts(family_path, required_fields=["title", "start", "end"])

    expected_conflicts = None
    expected_attendance = None
    if team_rows is not None and family_rows is not None:
        expected_conflicts = _compute_expected_conflicts(team_rows, family_rows)
        expected_attendance = _compute_expected_attendance(team_rows, family_rows)

    # Conflicts CSV grading
    conflicts_out = workspace / "output" / "conflicts.csv"
    if expected_conflicts is not None and conflicts_out.exists():
        try:
            with conflicts_out.open(newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames or []
                expected_header = [
                    "team_event_date",
                    "team_event_start",
                    "team_event_end",
                    "event_type",
                    "family_event_title",
                    "family_event_start",
                    "family_event_end",
                    "overlap_minutes",
                ]
                if header == expected_header:
                    scores["conflicts_header_correct"] = 1.0
                # Read all rows
                out_rows = list(reader)
                # Row count check
                if len(out_rows) == len(expected_conflicts):
                    scores["conflicts_row_count_correct"] = 1.0
                # Content comparison as multiset of tuples
                def norm_row(r: Dict[str, str]) -> Optional[Tuple]:
                    try:
                        # overlap_minutes should be integer
                        om = int(str(r.get("overlap_minutes", "")).strip())
                        tup = (
                            (r.get("team_event_date") or "").strip(),
                            (r.get("team_event_start") or "").strip(),
                            (r.get("team_event_end") or "").strip(),
                            (r.get("event_type") or "").strip(),
                            (r.get("family_event_title") or "").strip(),
                            (r.get("family_event_start") or "").strip(),
                            (r.get("family_event_end") or "").strip(),
                            str(om),
                        )
                        return tup
                    except Exception:
                        return None

                expected_tuples = []
                for er in expected_conflicts:
                    et = (
                        er["team_event_date"],
                        er["team_event_start"],
                        er["team_event_end"],
                        er["event_type"],
                        er["family_event_title"],
                        er["family_event_start"],
                        er["family_event_end"],
                        er["overlap_minutes"],
                    )
                    expected_tuples.append(et)
                out_tuples = []
                ok = True
                for r in out_rows:
                    t = norm_row(r)
                    if t is None:
                        ok = False
                        break
                    out_tuples.append(t)
                if ok:
                    if Counter(out_tuples) == Counter(expected_tuples):
                        scores["conflicts_rows_match"] = 1.0
        except Exception:
            pass  # keep zeros
    else:
        # If expected cannot be computed or file missing, leave zeros.
        pass

    # Attendance plan JSON grading
    attendance_out = workspace / "output" / "attendance_plan.json"
    attendance_data = None
    if attendance_out.exists():
        try:
            attendance_data = _load_json(attendance_out)
        except Exception:
            attendance_data = None

    if expected_attendance is not None and isinstance(attendance_data, list):
        scores["attendance_json_parseable"] = 1.0
        if len(attendance_data) == len(expected_attendance):
            scores["attendance_count_correct"] = 1.0

        # Build index for expected by (start, end, event_type)
        exp_index = {}
        for e in expected_attendance:
            key = (e["start"], e["end"], e["event_type"])
            exp_index[key] = e

        # Validate each record
        valid_all = True

        # Also ensure there are no duplicate keys and that keys match exactly the expected set
        found_keys = set()
        for item in attendance_data:
            if not isinstance(item, dict):
                valid_all = False
                break
            start = (item.get("start") or "").strip()
            end = (item.get("end") or "").strip()
            etype = (item.get("event_type") or "").strip()
            key = (start, end, etype)
            if key in found_keys:
                valid_all = False
                break
            found_keys.add(key)
            if key not in exp_index:
                valid_all = False
                break
            exp = exp_index[key]
            # Check required fields presence and values
            if (item.get("date") or "").strip() != exp["date"]:
                valid_all = False
                break
            if (item.get("attendance_required") or "").strip() != exp["attendance_required"]:
                valid_all = False
                break
            if (item.get("plan") or "").strip() != exp["plan"]:
                valid_all = False
                break
            # conflict_titles as list equality ignoring order
            ct = item.get("conflict_titles")
            if not isinstance(ct, list):
                valid_all = False
                break
            if sorted([str(x) for x in ct]) != sorted([str(x) for x in exp["conflict_titles"]]):
                valid_all = False
                break

        if valid_all and len(found_keys) == len(exp_index):
            scores["attendance_values_correct"] = 1.0

    # Email grading
    email_out = workspace / "output" / "email_to_coach.txt"
    email_text = None
    if email_out.exists():
        email_text = _read_text(email_out)

    # Load contacts for name checks and greeting
    contacts = _load_json(contacts_path) if contacts_path.exists() else None
    coach_name = contacts.get("coach_name") if isinstance(contacts, dict) else None
    parent_name = contacts.get("parent_name") if isinstance(contacts, dict) else None
    child_name = contacts.get("child_name") if isinstance(contacts, dict) else None
    team_name = contacts.get("team_name") if isinstance(contacts, dict) else None

    if email_text is not None and isinstance(email_text, str):
        trimmed = email_text.lstrip()
        # Greeting check only if we have coach name
        if isinstance(coach_name, str):
            expected_greeting = f"Hi {coach_name},"
            if trimmed.startswith(expected_greeting):
                scores["email_greeting_correct"] = 1.0
        # Names/team presence
        if isinstance(parent_name, str) and isinstance(child_name, str) and isinstance(team_name, str):
            if parent_name in email_text and child_name in email_text and team_name in email_text:
                scores["email_includes_names"] = 1.0

        # List events that need excuse
        if expected_attendance is not None:
            needs_excuse = [e for e in expected_attendance if e["plan"] == "Needs Excuse"]
            ok_list = True
            for e in needs_excuse:
                # Each should include event_type, start, end strings
                if (e["event_type"] not in email_text) or (e["start"] not in email_text) or (e["end"] not in email_text):
                    ok_list = False
                    break
            if ok_list:
                scores["email_lists_excuse_events"] = 1.0

        # Forms status
        req_docs = None
        if required_docs_path.exists():
            txt = _read_text(required_docs_path)
            if txt is not None:
                req_docs = [line.strip() for line in txt.splitlines() if line.strip()]
        forms_files = _list_dir_files(forms_dir) if forms_dir.exists() else None
        if isinstance(req_docs, list) and isinstance(forms_files, list):
            present = [d for d in req_docs if d in forms_files]
            missing = [d for d in req_docs if d not in forms_files]
            # Check that present ones are mentioned and missing ones are mentioned
            if present and missing:
                has_all_present = all(doc in email_text for doc in present)
                has_all_missing = all(doc in email_text for doc in missing)
                if has_all_present and has_all_missing:
                    scores["email_forms_status_mentioned"] = 1.0
            elif present and not missing:
                # Edge case: no missing files
                if all(doc in email_text for doc in present):
                    scores["email_forms_status_mentioned"] = 1.0
            elif missing and not present:
                if all(doc in email_text for doc in missing):
                    scores["email_forms_status_mentioned"] = 1.0

        # Closing with name (last non-empty line contains parent name)
        if isinstance(parent_name, str):
            lines = [ln.rstrip("\r") for ln in email_text.splitlines()]
            last_non_empty = ""
            for ln in reversed(lines):
                if ln.strip():
                    last_non_empty = ln.strip()
                    break
            if parent_name in last_non_empty:
                scores["email_closes_with_name"] = 1.0

        # No attachment claims
        lower_email = email_text.lower()
        if "attach" not in lower_email:
            scores["email_no_attachment_claim"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()