import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_simple_yaml(path: Path) -> Optional[Dict[str, str]]:
    """
    Minimal YAML loader for simple key: value pairs.
    Ignores comments and empty lines.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    data: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            # malformed for our simple needs
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove surrounding quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        data[key] = val
    return data


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def _compute_expected_stats(workspace: Path) -> Optional[Dict[str, Any]]:
    contacts_path = workspace / "input" / "contacts.csv"
    achievements_path = workspace / "input" / "achievements.csv"
    event_path = workspace / "input" / "event.yaml"

    contacts = _load_csv_rows(contacts_path)
    achievements = _load_csv_rows(achievements_path)
    event = _load_simple_yaml(event_path)

    if contacts is None or achievements is None or event is None:
        return None

    # Event fields
    event_title = event.get("title")
    event_date = event.get("date")
    event_location = event.get("location")
    rsvp_deadline = event.get("rsvp_deadline")
    if not (event_title and event_date and event_location and rsvp_deadline):
        return None

    # Counts
    total_contacts = len(contacts)
    rsvp_yes = sum(1 for c in contacts if (c.get("rsvp_status") or "").strip().lower() == "yes")
    rsvp_no = sum(1 for c in contacts if (c.get("rsvp_status") or "").strip().lower() == "no")
    rsvp_pending = sum(1 for c in contacts if (c.get("rsvp_status") or "").strip().lower() == "pending")
    rsvp_rate_yes = round((rsvp_yes / total_contacts) if total_contacts > 0 else 0.0, 2)

    # By sport
    sports = {}
    for c in contacts:
        sport = (c.get("sport") or "").strip()
        status = (c.get("rsvp_status") or "").strip().lower()
        if not sport:
            continue
        if sport not in sports:
            sports[sport] = {"contacts": 0, "rsvp_yes": 0, "rsvp_no": 0, "rsvp_pending": 0}
        sports[sport]["contacts"] += 1
        if status == "yes":
            sports[sport]["rsvp_yes"] += 1
        elif status == "no":
            sports[sport]["rsvp_no"] += 1
        elif status == "pending":
            sports[sport]["rsvp_pending"] += 1

    # Championships by sport
    championships_by_sport: Dict[str, int] = {}
    championships_total = 0
    for a in achievements:
        title = (a.get("title") or "").strip()
        sport = (a.get("sport") or "").strip()
        if title == "State Championship" and sport:
            championships_by_sport[sport] = championships_by_sport.get(sport, 0) + 1
            championships_total += 1

    by_sport = {}
    for sport, counts in sports.items():
        by_sport[sport] = {
            "contacts": counts["contacts"],
            "rsvp_yes": counts["rsvp_yes"],
            "rsvp_no": counts["rsvp_no"],
            "rsvp_pending": counts["rsvp_pending"],
            "championships": championships_by_sport.get(sport, 0),
        }

    return {
        "event": {
            "title": event_title,
            "date": event_date,
            "location": event_location,
            "rsvp_deadline": rsvp_deadline,
        },
        "overall": {
            "total_contacts": total_contacts,
            "rsvp_yes": rsvp_yes,
            "rsvp_no": rsvp_no,
            "rsvp_pending": rsvp_pending,
            "rsvp_rate_yes": rsvp_rate_yes,
        },
        "by_sport": by_sport,
        "championships_total": championships_total,
        "contacts": contacts,  # include for downstream verification
    }


def _float_equal_2dp(a: Any, b: Any) -> bool:
    try:
        return round(float(a), 2) == round(float(b), 2)
    except Exception:
        return False


def _load_messages_pending(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _load_csv_rows(path)
    if rows is None:
        return None
    # Verify expected columns presence
    expected_cols = ["name", "contact_method", "destination", "subject", "body"]
    # Check header order exactly
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return None
    if header != expected_cols:
        # Even if rows loaded, if header not exactly as expected, treat as malformed for structure check
        return rows  # We'll handle structure check separately using header; still return rows for other checks
    return rows


def _extract_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            return header
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_event_fields_correct": 0.0,
        "summary_overall_counts_correct": 0.0,
        "summary_by_sport_counts_correct": 0.0,
        "summary_championships_total_correct": 0.0,
        "messages_pending_structure_and_recipients_correct": 0.0,
        "messages_pending_body_includes_required_context": 0.0,
        "messages_pending_cross_validates_with_summary": 0.0,
        "reminder_plan_send_dates_correct": 0.0,
        "reminder_plan_recipients_correct": 0.0,
        "output_contains_only_expected_files": 0.0,
    }

    # Compute expected from inputs
    expected = _compute_expected_stats(workspace)
    summary_path = workspace / "output" / "summary_stats.json"
    messages_path = workspace / "output" / "messages_pending.csv"
    reminder_path = workspace / "output" / "reminder_plan.json"

    summary = _load_json(summary_path)
    # Summary checks
    if expected is not None and isinstance(summary, dict):
        # Event fields
        event_expected = {
            "title": expected["event"]["title"],
            "date": expected["event"]["date"],
            "rsvp_deadline": expected["event"]["rsvp_deadline"],
        }
        event_got = summary.get("event") if isinstance(summary.get("event"), dict) else None
        if event_got is not None:
            ok = (
                event_got.get("title") == event_expected["title"]
                and event_got.get("date") == event_expected["date"]
                and event_got.get("rsvp_deadline") == event_expected["rsvp_deadline"]
            )
            if ok:
                scores["summary_event_fields_correct"] = 1.0

        # Overall counts
        overall_got = summary.get("overall") if isinstance(summary.get("overall"), dict) else None
        if overall_got is not None:
            og = overall_got
            oe = expected["overall"]
            ok_overall = (
                og.get("total_contacts") == oe["total_contacts"]
                and og.get("rsvp_yes") == oe["rsvp_yes"]
                and og.get("rsvp_no") == oe["rsvp_no"]
                and og.get("rsvp_pending") == oe["rsvp_pending"]
                and _float_equal_2dp(og.get("rsvp_rate_yes"), oe["rsvp_rate_yes"])
            )
            if ok_overall:
                scores["summary_overall_counts_correct"] = 1.0

        # By sport counts
        by_sport_got = summary.get("by_sport") if isinstance(summary.get("by_sport"), dict) else None
        if by_sport_got is not None:
            expected_sports = set(expected["by_sport"].keys())
            got_sports = set(by_sport_got.keys())
            # Require exactly the same sports as in contacts.csv
            if got_sports == expected_sports:
                per_sport_ok = True
                for sport in expected_sports:
                    exp = expected["by_sport"][sport]
                    got = by_sport_got.get(sport, {})
                    if not (
                        isinstance(got, dict)
                        and got.get("contacts") == exp["contacts"]
                        and got.get("rsvp_yes") == exp["rsvp_yes"]
                        and got.get("rsvp_no") == exp["rsvp_no"]
                        and got.get("rsvp_pending") == exp["rsvp_pending"]
                        and got.get("championships") == exp["championships"]
                    ):
                        per_sport_ok = False
                        break
                if per_sport_ok:
                    scores["summary_by_sport_counts_correct"] = 1.0

        # Championships total
        ct_got = summary.get("championships_total")
        if ct_got == expected["championships_total"]:
            scores["summary_championships_total_correct"] = 1.0

    # Messages checks
    messages_rows = _load_messages_pending(messages_path)  # may be None
    header = _extract_header(messages_path) if messages_path.exists() else None
    if expected is not None and messages_rows is not None and isinstance(messages_rows, list):
        expected_cols = ["name", "contact_method", "destination", "subject", "body"]
        structure_ok = header == expected_cols

        # Build expected recipient set (non-yes contacts)
        non_yes_contacts = [c for c in expected["contacts"] if (c.get("rsvp_status") or "").strip().lower() != "yes"]
        # Sort expected by sport then name
        exp_sorted = sorted(
            non_yes_contacts,
            key=lambda c: ((c.get("sport") or "").strip(), (c.get("name") or "").strip()),
        )
        # Verify row count
        count_ok = len(messages_rows) == len(exp_sorted)

        # Build mapping to expected destination
        def expected_dest(c: Dict[str, str]) -> str:
            method = (c.get("preferred_contact_method") or "").strip().lower()
            if method == "email":
                return (c.get("email") or "").strip()
            else:
                return (c.get("phone") or "").strip()

        # Check recipients, contact_method/destination/subject per row, and ordering by sport then name
        recipients_ok = True
        ordering_ok = True
        # Map actual rows by unique key (name, contact_method, destination)
        # Also build a list of tuples for ordering check
        name_method_dest_to_row: Dict[tuple, Dict[str, str]] = {}
        actual_order_keys: List[tuple] = []
        # Need mapping from these keys to sport via contacts
        contact_index_by_key: Dict[tuple, Dict[str, str]] = {}
        for c in expected["contacts"]:
            cm = (c.get("preferred_contact_method") or "").strip().lower()
            dest = expected_dest(c)
            key = ((c.get("name") or "").strip(), cm, dest)
            contact_index_by_key[key] = c

        for row in messages_rows:
            name = (row.get("name") or "").strip()
            cm = (row.get("contact_method") or "").strip().lower()
            dest = (row.get("destination") or "").strip()
            key = (name, cm, dest)
            name_method_dest_to_row[key] = row
            # Determine sport for ordering
            c = contact_index_by_key.get(key)
            if c is not None:
                sport = (c.get("sport") or "").strip()
            else:
                sport = ""
            actual_order_keys.append((sport, name))

        # Check each expected recipient exists and fields match
        for c in non_yes_contacts:
            name = (c.get("name") or "").strip()
            cm = (c.get("preferred_contact_method") or "").strip().lower()
            dest = expected_dest(c)
            key = (name, cm, dest)
            row = name_method_dest_to_row.get(key)
            if row is None:
                recipients_ok = False
                break
            # Subject rules
            subj = row.get("subject", "")
            if cm == "email":
                if subj != "Follow-up: RSVP for State Champions Reunion":
                    recipients_ok = False
                    break
            else:
                if (subj or "").strip() != "":
                    recipients_ok = False
                    break

        # Ordering: should be by sport then name ascending
        expected_order_keys = [((c.get("sport") or "").strip(), (c.get("name") or "").strip()) for c in exp_sorted]
        if actual_order_keys != expected_order_keys:
            ordering_ok = False

        if structure_ok and count_ok and recipients_ok and ordering_ok:
            scores["messages_pending_structure_and_recipients_correct"] = 1.0

        # Body includes required context
        context_ok = True
        # Event fields
        ev = expected["event"]
        title = ev["title"]
        date_str = ev["date"]
        location = ev["location"]
        deadline = ev["rsvp_deadline"]

        for c in non_yes_contacts:
            name = (c.get("name") or "").strip()
            cm = (c.get("preferred_contact_method") or "").strip().lower()
            dest = expected_dest(c)
            key = (name, cm, dest)
            row = name_method_dest_to_row.get(key)
            if row is None:
                context_ok = False
                break
            body = (row.get("body") or "")
            # Check event.title, event.date, event.location, rsvp_deadline, sport
            if not (title in body and date_str in body and location in body and deadline in body):
                context_ok = False
                break
            sport = (c.get("sport") or "").strip()
            if sport and sport not in body:
                context_ok = False
                break
            # Check "fellow Westwood Panther" and "state champion" and "RSVP" and "attend" presence (case-insensitive)
            body_lower = body.lower()
            if ("westwood panther" not in body_lower) or ("state champion" not in body_lower) or ("rsvp" not in body_lower) or ("attend" not in body_lower):
                context_ok = False
                break

        if context_ok:
            scores["messages_pending_body_includes_required_context"] = 1.0

        # Cross-validation with summary: numbers in body must match summary values
        cross_ok = True
        if isinstance(summary, dict):
            by_sport_got = summary.get("by_sport") if isinstance(summary.get("by_sport"), dict) else {}
            overall_got = summary.get("overall") if isinstance(summary.get("overall"), dict) else {}
            try:
                overall_rate = overall_got.get("rsvp_rate_yes", None)
                overall_rate_str = f"{float(overall_rate):.2f}"
            except Exception:
                overall_rate_str = None
            for c in non_yes_contacts:
                name = (c.get("name") or "").strip()
                cm = (c.get("preferred_contact_method") or "").strip().lower()
                dest = expected_dest(c)
                key = (name, cm, dest)
                row = name_method_dest_to_row.get(key)
                if row is None:
                    cross_ok = False
                    break
                body = (row.get("body") or "")
                sport = (c.get("sport") or "").strip()
                bs = by_sport_got.get(sport, {})
                if not isinstance(bs, dict):
                    cross_ok = False
                    break
                # Values to check
                rsvp_yes_sport = bs.get("rsvp_yes", None)
                championships_sport = bs.get("championships", None)
                if rsvp_yes_sport is None or championships_sport is None or overall_rate_str is None:
                    cross_ok = False
                    break
                # Check tokenized presence for integers and exact substring for rate
                if not re.search(rf"\b{re.escape(str(int(rsvp_yes_sport)))}\b", body):
                    cross_ok = False
                    break
                if not re.search(rf"\b{re.escape(str(int(championships_sport)))}\b", body):
                    cross_ok = False
                    break
                if overall_rate_str not in body:
                    cross_ok = False
                    break
        else:
            cross_ok = False

        if cross_ok:
            scores["messages_pending_cross_validates_with_summary"] = 1.0

    # Reminder plan checks
    reminder = _load_json(reminder_path)
    if expected is not None and isinstance(reminder, dict):
        ev = expected["event"]
        deadline_date = _parse_date(ev["rsvp_deadline"])
        if deadline_date is not None:
            first_date = (deadline_date - timedelta(days=7)).strftime("%Y-%m-%d")
            last_date = (deadline_date - timedelta(days=2)).strftime("%Y-%m-%d")
            first = reminder.get("first_reminder")
            last = reminder.get("last_reminder")
            if isinstance(first, dict) and isinstance(last, dict):
                if first.get("send_date") == first_date and last.get("send_date") == last_date:
                    scores["reminder_plan_send_dates_correct"] = 1.0

                # Verify recipients lists
                def normalize_recipients(lst: Any) -> Optional[List[Dict[str, Any]]]:
                    if not isinstance(lst, list):
                        return None
                    norm = []
                    for item in lst:
                        if not isinstance(item, dict):
                            return None
                        norm.append(item)
                    return norm

                first_recipients = normalize_recipients(first.get("recipients"))
                last_recipients = normalize_recipients(last.get("recipients"))

                def expected_recipient_objs() -> List[Dict[str, Any]]:
                    objs = []
                    for c in expected["contacts"]:
                        if (c.get("rsvp_status") or "").strip().lower() == "yes":
                            continue
                        cm = (c.get("preferred_contact_method") or "").strip().lower()
                        dest = (c.get("email") or "").strip() if cm == "email" else (c.get("phone") or "").strip()
                        objs.append({
                            "name": (c.get("name") or "").strip(),
                            "sport": (c.get("sport") or "").strip(),
                            "contact_method": cm,
                            "destination": dest,
                            "rsvp_status": (c.get("rsvp_status") or "").strip(),
                        })
                    # For comparison ignore order: sort by sport then name
                    objs_sorted = sorted(objs, key=lambda x: (x["sport"], x["name"]))
                    return objs_sorted

                def validate_recipient_list(actual: Optional[List[Dict[str, Any]]]) -> bool:
                    if actual is None:
                        return False
                    # normalize actual to only required keys and check exact keys
                    required_keys = {"name", "sport", "contact_method", "destination", "rsvp_status"}
                    processed = []
                    for item in actual:
                        keys_set = set(item.keys())
                        # Require exactly the required keys
                        if keys_set != required_keys:
                            return False
                        processed.append({
                            "name": (item.get("name") or "").strip(),
                            "sport": (item.get("sport") or "").strip(),
                            "contact_method": (item.get("contact_method") or "").strip().lower(),
                            "destination": (item.get("destination") or "").strip(),
                            "rsvp_status": (item.get("rsvp_status") or "").strip(),
                        })
                    processed_sorted = sorted(processed, key=lambda x: (x["sport"], x["name"]))
                    return processed_sorted == expected_recipient_objs()

                if validate_recipient_list(first_recipients) and validate_recipient_list(last_recipients):
                    scores["reminder_plan_recipients_correct"] = 1.0

    # Output directory contents check
    output_dir = workspace / "output"
    expected_files = {"summary_stats.json", "messages_pending.csv", "reminder_plan.json"}
    if output_dir.exists() and output_dir.is_dir():
        actual_files = {p.name for p in output_dir.iterdir() if p.is_file()}
        if actual_files == expected_files:
            scores["output_contains_only_expected_files"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()