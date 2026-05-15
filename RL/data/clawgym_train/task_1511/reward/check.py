import csv
import json
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [dict(row) for row in reader]
            return rows, header
    except Exception:
        return None


def _load_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    # Very simple YAML parser for flat key: value pairs with scalars (strings or numbers)
    try:
        data: Dict[str, Any] = {}
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove surrounding quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            # Try to parse numbers
            if re.fullmatch(r"-?\d+", val):
                data[key] = int(val)
            else:
                data[key] = val
        return data
    except Exception:
        return None


def _parse_iso8601_utc(ts: str) -> Optional[datetime]:
    try:
        # Normalize Z to +00:00
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _scan_csv_files(directory: Path) -> List[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted([p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".csv"])


def _load_guest_list(guest_path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    read = _read_csv_dicts(guest_path)
    if read is None:
        return None
    rows, header = read
    expected_cols = ["name", "email", "group"]
    for col in expected_cols:
        if col not in header:
            return None
    guests: Dict[str, Dict[str, str]] = {}
    for r in rows:
        email = (r.get("email") or "").strip()
        name = (r.get("name") or "").strip()
        group = (r.get("group") or "").strip()
        if not email or not name or not group:
            # malformed row; treat as failure
            return None
        guests[email] = {"name": name, "email": email, "group": group}
    return guests


def _normalize_response(resp: str) -> Optional[str]:
    if resp is None:
        return None
    resp_l = resp.strip().lower()
    if resp_l == "yes":
        return "Yes"
    if resp_l == "no":
        return "No"
    if resp_l == "maybe":
        return "Maybe"
    return None


def _safe_int(value: Any, default: int = 0) -> Optional[int]:
    try:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return default
        return int(str(value).strip())
    except Exception:
        return None


def _compute_expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    guest_path = workspace / "input" / "guest_list.csv"
    rsvps_dir = workspace / "input" / "rsvps"
    event_yaml = workspace / "input" / "event_details.yaml"
    capacity_path = workspace / "input" / "venue_capacity.txt"

    guests = _load_guest_list(guest_path)
    if guests is None:
        return None

    allowed_emails = set(guests.keys())

    # Load RSVPs
    rsvp_files = _scan_csv_files(rsvps_dir)
    combined: List[Dict[str, Any]] = []
    for rf in rsvp_files:
        read = _read_csv_dicts(rf)
        if read is None:
            return None
        rows, header = read
        # Expect these columns to exist at least: email,response,plus_ones,timestamp_iso
        for col in ["email", "response", "timestamp_iso"]:
            if col not in header:
                return None
        # plus_ones may be missing - but in inputs it's present; if missing we still handle default
        for r in rows:
            email = (r.get("email") or "").strip()
            if not email:
                return None
            response = _normalize_response(r.get("response"))
            if response is None:
                return None
            ts_str = (r.get("timestamp_iso") or "").strip()
            ts = _parse_iso8601_utc(ts_str)
            if ts is None:
                return None
            plus_ones_raw = r.get("plus_ones", "")
            plus_ones = _safe_int(plus_ones_raw, 0)
            if plus_ones is None:
                return None
            combined.append({
                "email": email,
                "response": response,
                "plus_ones": plus_ones,
                "timestamp_iso": ts_str,
                "timestamp": ts,
            })

    # Filter to allowed emails
    combined = [r for r in combined if r["email"] in allowed_emails]

    # Deduplicate latest by email using max timestamp
    latest: Dict[str, Dict[str, Any]] = {}
    for r in combined:
        e = r["email"]
        if e not in latest or r["timestamp"] > latest[e]["timestamp"]:
            latest[e] = r

    # Prepare expected latest_rsvp rows as dict per email
    expected_latest = {}
    for e, r in latest.items():
        expected_latest[e] = {
            "email": e,
            "response": r["response"],
            "plus_ones": int(r["plus_ones"]),
            "timestamp_iso": r["timestamp_iso"],
        }

    # Attendance summary values
    total_invited = len(guests)
    total_responded = len(expected_latest)
    yes_count = sum(1 for r in expected_latest.values() if r["response"] == "Yes")
    no_count = sum(1 for r in expected_latest.values() if r["response"] == "No")
    maybe_count = sum(1 for r in expected_latest.values() if r["response"] == "Maybe")
    expected_headcount_yes = sum(1 + r["plus_ones"] for r in expected_latest.values() if r["response"] == "Yes")

    # Capacity
    capacity_text = _safe_read_text(capacity_path)
    if capacity_text is None:
        return None
    capacity_str = capacity_text.strip()
    try:
        capacity = int(capacity_str.split()[0])
    except Exception:
        return None
    capacity_remaining = capacity - expected_headcount_yes

    expected_attendance_summary = {
        "total_invited": total_invited,
        "total_responded": total_responded,
        "yes_count": yes_count,
        "no_count": no_count,
        "maybe_count": maybe_count,
        "expected_headcount_yes_incl_plus_ones": expected_headcount_yes,
        "capacity": capacity,
        "capacity_remaining": capacity_remaining,
    }

    # Group breakdown
    groups: Dict[str, Dict[str, int]] = {}
    # Initialize groups from guest list
    for email, info in guests.items():
        grp = info["group"]
        if grp not in groups:
            groups[grp] = {
                "invited_count": 0,
                "responded_count": 0,
                "yes_count": 0,
                "no_count": 0,
                "maybe_count": 0,
                "yes_headcount": 0,
            }
        groups[grp]["invited_count"] += 1
    # Tally responses
    for email, r in expected_latest.items():
        grp = guests[email]["group"]
        groups[grp]["responded_count"] += 1
        if r["response"] == "Yes":
            groups[grp]["yes_count"] += 1
            groups[grp]["yes_headcount"] += 1 + int(r["plus_ones"])
        elif r["response"] == "No":
            groups[grp]["no_count"] += 1
        elif r["response"] == "Maybe":
            groups[grp]["maybe_count"] += 1

    # Unresponded list
    unresponded = []
    for email, info in guests.items():
        if email not in expected_latest:
            unresponded.append({
                "name": info["name"],
                "email": info["email"],
                "group": info["group"],
            })

    # Event details
    event_details = _load_simple_yaml(event_yaml)
    if event_details is None:
        return None

    # First names by email
    first_names: Dict[str, str] = {}
    for email, info in guests.items():
        name = info["name"].strip()
        first = name.split()[0] if name else ""
        first_names[email] = first

    return {
        "guests": guests,
        "expected_latest": expected_latest,
        "expected_attendance_summary": expected_attendance_summary,
        "expected_group_breakdown": groups,
        "expected_unresponded": unresponded,
        "event_details": event_details,
        "first_names": first_names,
        "yes_emails": sorted([e for e, r in expected_latest.items() if r["response"] == "Yes"]),
        "unresponded_emails": sorted([x["email"] for x in unresponded]),
    }


def _read_latest_rsvp_output(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    return _read_csv_dicts(path)


def _check_latest_rsvp_columns(header: Optional[List[str]]) -> float:
    if header is None:
        return 0.0
    expected = ["email", "response", "plus_ones", "timestamp_iso"]
    return 1.0 if header == expected else 0.0


def _compare_latest_rsvp_rows(rows: List[Dict[str, str]], expected_latest: Dict[str, Dict[str, Any]]) -> float:
    # Must have exactly one row per expected email and match values, no extras
    # Build map from email -> row
    found_emails = set()
    found_map: Dict[str, Dict[str, str]] = {}
    for r in rows:
        email = (r.get("email") or "").strip()
        if email:
            if email in found_map:
                # duplicate email rows
                return 0.0
            found_map[email] = r
            found_emails.add(email)
    if found_emails != set(expected_latest.keys()):
        return 0.0
    # Check values
    for email, exp in expected_latest.items():
        row = found_map.get(email)
        if row is None:
            return 0.0
        # Response exact match
        resp = (row.get("response") or "").strip()
        if resp != exp["response"]:
            return 0.0
        # plus_ones must parse to int and equal
        po_str = (row.get("plus_ones") or "").strip()
        try:
            po_val = int(po_str)
        except Exception:
            return 0.0
        if po_val != int(exp["plus_ones"]):
            return 0.0
        # timestamp exact match
        ts = (row.get("timestamp_iso") or "").strip()
        if ts != exp["timestamp_iso"]:
            return 0.0
    return 1.0


def _read_single_row_csv(path: Path) -> Optional[Tuple[Dict[str, str], List[str]]]:
    read = _read_csv_dicts(path)
    if read is None:
        return None
    rows, header = read
    if header is None:
        return None
    if len(rows) != 1:
        # must be single row
        return None
    return rows[0], header


def _check_attendance_summary(row: Dict[str, str], header: List[str], expected: Dict[str, int]) -> Tuple[float, float]:
    expected_cols = ["total_invited", "total_responded", "yes_count", "no_count", "maybe_count",
                     "expected_headcount_yes_incl_plus_ones", "capacity", "capacity_remaining"]
    cols_ok = 1.0 if header == expected_cols else 0.0
    if cols_ok == 0.0:
        return 0.0, 0.0
    # Parse and compare numeric values
    parsed: Dict[str, Optional[int]] = {}
    for k in expected_cols:
        val = (row.get(k) or "").strip()
        try:
            parsed[k] = int(val)
        except Exception:
            parsed[k] = None
    vals_ok = all(parsed.get(k) == expected[k] for k in expected_cols)
    return cols_ok, 1.0 if vals_ok else 0.0


def _read_group_breakdown(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    return _read_csv_dicts(path)


def _check_group_breakdown(rows: List[Dict[str, str]], header: List[str], expected_groups: Dict[str, Dict[str, int]]) -> Tuple[float, float]:
    expected_cols = ["group", "invited_count", "responded_count", "yes_count", "no_count", "maybe_count", "yes_headcount"]
    cols_ok = 1.0 if header == expected_cols else 0.0
    if cols_ok == 0.0:
        return 0.0, 0.0
    # Build map from group -> dict of ints
    got_groups = {}
    for r in rows:
        g = (r.get("group") or "").strip()
        if not g:
            return 0.0, 0.0
        try:
            got_groups[g] = {
                "invited_count": int((r.get("invited_count") or "").strip()),
                "responded_count": int((r.get("responded_count") or "").strip()),
                "yes_count": int((r.get("yes_count") or "").strip()),
                "no_count": int((r.get("no_count") or "").strip()),
                "maybe_count": int((r.get("maybe_count") or "").strip()),
                "yes_headcount": int((r.get("yes_headcount") or "").strip()),
            }
        except Exception:
            return 0.0, 0.0
    if set(got_groups.keys()) != set(expected_groups.keys()):
        return cols_ok, 0.0
    for g, expvals in expected_groups.items():
        got = got_groups.get(g)
        if got is None:
            return cols_ok, 0.0
        for k, v in expvals.items():
            if got.get(k) != v:
                return cols_ok, 0.0
    return cols_ok, 1.0


def _read_unresponded(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    return _read_csv_dicts(path)


def _check_unresponded(rows: List[Dict[str, str]], header: List[str], expected_unresponded: List[Dict[str, str]]) -> Tuple[float, float]:
    expected_cols = ["name", "email", "group"]
    cols_ok = 1.0 if header == expected_cols else 0.0
    if cols_ok == 0.0:
        return 0.0, 0.0
    # Compare sets of tuples (name,email,group)
    got_set = set()
    for r in rows:
        name = (r.get("name") or "").strip()
        email = (r.get("email") or "").strip()
        group = (r.get("group") or "").strip()
        if not name or not email or not group:
            return cols_ok, 0.0
        got_set.add((name, email, group))
    exp_set = set((r["name"], r["email"], r["group"]) for r in expected_unresponded)
    vals_ok = 1.0 if got_set == exp_set else 0.0
    return cols_ok, vals_ok


def _list_message_files(dir_path: Path) -> List[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    files = []
    for p in dir_path.iterdir():
        if p.is_file() and p.suffix.lower() == ".txt":
            files.append(p)
    return sorted(files)


def _load_message(path: Path) -> Optional[str]:
    return _safe_read_text(path)


def _check_confirmation_content(text: str, email: str, first_name: str, party_size: int, event: Dict[str, Any]) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    if not lines:
        return False
    # First line must be To: <email>
    if not lines[0].startswith("To:"):
        return False
    if lines[0] != f"To: {email}":
        return False
    # Subject line with event_name
    subj_lines = [ln for ln in lines if ln.lower().startswith("subject:")]
    if not subj_lines:
        return False
    event_name = str(event.get("event_name", ""))
    if not event_name or event_name not in subj_lines[0]:
        return False
    # Greet by first name (presence check)
    if first_name.lower() not in text.lower():
        return False
    # Confirm attendance and mention total party size (look for line containing number and a keyword)
    ps_str = str(party_size)
    keywords = ["party", "attend", "attending", "guests", "people", "headcount"]
    found_ps = False
    for ln in lines:
        if ps_str in ln and any(kw in ln.lower() for kw in keywords):
            found_ps = True
            break
    if not found_ps:
        return False
    # Include date, time, and location
    if str(event.get("date", "")) not in text:
        return False
    if str(event.get("time", "")) not in text:
        return False
    if str(event.get("location", "")) not in text:
        return False
    # Arrival buffer: "arrive" and minutes number on same line
    buffer_min = str(event.get("arrival_buffer_minutes", ""))
    if not buffer_min:
        return False
    found_arrival = False
    for ln in lines:
        if ("arrive" in ln.lower()) and (buffer_min in ln):
            found_arrival = True
            break
    if not found_arrival:
        return False
    # Remind to keep it a surprise
    if "surprise" not in text.lower():
        return False
    # Include organizer_name and contact_phone
    if str(event.get("organizer_name", "")) not in text:
        return False
    if str(event.get("contact_phone", "")) not in text:
        return False
    return True


def _check_reminder_content(text: str, email: str, first_name: str, event: Dict[str, Any]) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    if not lines:
        return False
    # First line must be To: <email>
    if not lines[0].startswith("To:"):
        return False
    if lines[0] != f"To: {email}":
        return False
    # Subject line includes event_name and "RSVP"
    subj_lines = [ln for ln in lines if ln.lower().startswith("subject:")]
    if not subj_lines:
        return False
    subj = subj_lines[0]
    event_name = str(event.get("event_name", ""))
    if not event_name or (event_name not in subj):
        return False
    if "rsvp" not in subj.lower():
        return False
    # Greeting includes first name
    if first_name.lower() not in text.lower():
        return False
    # Politely ask to RSVP: look for "RSVP" somewhere in body
    if "rsvp" not in text.lower():
        return False
    # Include date, time, location
    if str(event.get("date", "")) not in text:
        return False
    if str(event.get("time", "")) not in text:
        return False
    if str(event.get("location", "")) not in text:
        return False
    # Remind to keep it a surprise
    if "surprise" not in text.lower():
        return False
    # Include organizer_name and contact_phone
    if str(event.get("organizer_name", "")) not in text:
        return False
    if str(event.get("contact_phone", "")) not in text:
        return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "latest_rsvp_file_exists": 0.0,
        "latest_rsvp_columns_correct": 0.0,
        "latest_rsvp_values_correct": 0.0,
        "attendance_summary_file_exists": 0.0,
        "attendance_summary_columns_correct": 0.0,
        "attendance_summary_values_correct": 0.0,
        "group_breakdown_file_exists": 0.0,
        "group_breakdown_columns_correct": 0.0,
        "group_breakdown_values_correct": 0.0,
        "unresponded_file_exists": 0.0,
        "unresponded_columns_correct": 0.0,
        "unresponded_rows_correct": 0.0,
        "confirmations_files_complete_set": 0.0,
        "confirmations_content_quality": 0.0,
        "reminders_files_complete_set": 0.0,
        "reminders_content_quality": 0.0,
    }

    expected = _compute_expected_from_inputs(workspace)

    # Paths to outputs
    latest_rsvp_path = workspace / "output" / "working" / "latest_rsvp.csv"
    attendance_summary_path = workspace / "output" / "summary" / "attendance_summary.csv"
    group_breakdown_path = workspace / "output" / "summary" / "group_breakdown.csv"
    unresponded_path = workspace / "output" / "summary" / "unresponded.csv"
    confirmations_dir = workspace / "output" / "messages" / "confirmations"
    reminders_dir = workspace / "output" / "messages" / "reminders"

    # Check latest_rsvp.csv
    if latest_rsvp_path.exists():
        scores["latest_rsvp_file_exists"] = 1.0
        read = _read_latest_rsvp_output(latest_rsvp_path)
        if read is not None:
            rows, header = read
            scores["latest_rsvp_columns_correct"] = _check_latest_rsvp_columns(header)
            if expected is not None and scores["latest_rsvp_columns_correct"] == 1.0:
                scores["latest_rsvp_values_correct"] = _compare_latest_rsvp_rows(rows, expected["expected_latest"])
            else:
                scores["latest_rsvp_values_correct"] = 0.0
        else:
            scores["latest_rsvp_columns_correct"] = 0.0
            scores["latest_rsvp_values_correct"] = 0.0
    else:
        scores["latest_rsvp_file_exists"] = 0.0

    # Check attendance_summary.csv
    if attendance_summary_path.exists():
        scores["attendance_summary_file_exists"] = 1.0
        sr = _read_single_row_csv(attendance_summary_path)
        if sr is not None and expected is not None:
            row, header = sr
            cols_ok, vals_ok = _check_attendance_summary(row, header, expected["expected_attendance_summary"])
            scores["attendance_summary_columns_correct"] = cols_ok
            scores["attendance_summary_values_correct"] = vals_ok
        else:
            scores["attendance_summary_columns_correct"] = 0.0
            scores["attendance_summary_values_correct"] = 0.0
    else:
        scores["attendance_summary_file_exists"] = 0.0

    # Check group_breakdown.csv
    if group_breakdown_path.exists():
        scores["group_breakdown_file_exists"] = 1.0
        read = _read_group_breakdown(group_breakdown_path)
        if read is not None and expected is not None:
            rows, header = read
            cols_ok, vals_ok = _check_group_breakdown(rows, header, expected["expected_group_breakdown"])
            scores["group_breakdown_columns_correct"] = cols_ok
            scores["group_breakdown_values_correct"] = vals_ok
        else:
            scores["group_breakdown_columns_correct"] = 0.0
            scores["group_breakdown_values_correct"] = 0.0
    else:
        scores["group_breakdown_file_exists"] = 0.0

    # Check unresponded.csv
    if unresponded_path.exists():
        scores["unresponded_file_exists"] = 1.0
        read = _read_unresponded(unresponded_path)
        if read is not None and expected is not None:
            rows, header = read
            cols_ok, vals_ok = _check_unresponded(rows, header, expected["expected_unresponded"])
            scores["unresponded_columns_correct"] = cols_ok
            scores["unresponded_rows_correct"] = vals_ok
        else:
            scores["unresponded_columns_correct"] = 0.0
            scores["unresponded_rows_correct"] = 0.0
    else:
        scores["unresponded_file_exists"] = 0.0

    # Confirmations messages
    if confirmations_dir.exists() and expected is not None:
        files = _list_message_files(confirmations_dir)
        got_emails = sorted([p.name for p in files])
        expected_emails = sorted([f"{e}.txt" for e in expected["yes_emails"]])
        scores["confirmations_files_complete_set"] = 1.0 if got_emails == expected_emails else 0.0

        # Content checks: all files must pass content to receive 1.0
        all_ok = True
        for e in expected["yes_emails"]:
            p = confirmations_dir / f"{e}.txt"
            txt = _load_message(p)
            if txt is None:
                all_ok = False
                break
            first_name = expected["first_names"].get(e, "")
            party_size = 1 + expected["expected_latest"][e]["plus_ones"]
            if not _check_confirmation_content(txt, e, first_name, party_size, expected["event_details"]):
                all_ok = False
                break
        scores["confirmations_content_quality"] = 1.0 if all_ok and expected_emails == got_emails else 0.0
    else:
        scores["confirmations_files_complete_set"] = 0.0
        scores["confirmations_content_quality"] = 0.0

    # Reminders messages
    if reminders_dir.exists() and expected is not None:
        files = _list_message_files(reminders_dir)
        got_emails = sorted([p.name for p in files])
        expected_emails = sorted([f"{e}.txt" for e in expected["unresponded_emails"]])
        scores["reminders_files_complete_set"] = 1.0 if got_emails == expected_emails else 0.0

        all_ok = True
        for e in expected["unresponded_emails"]:
            p = reminders_dir / f"{e}.txt"
            txt = _load_message(p)
            if txt is None:
                all_ok = False
                break
            first_name = expected["first_names"].get(e, "")
            if not _check_reminder_content(txt, e, first_name, expected["event_details"]):
                all_ok = False
                break
        scores["reminders_content_quality"] = 1.0 if all_ok and expected_emails == got_emails else 0.0
    else:
        scores["reminders_files_complete_set"] = 0.0
        scores["reminders_content_quality"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    # Keep key order as defined in the scores dict (no sort_keys) for downstream comparison
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()