import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


EXPECTED_FIELDS = [
    "reminder_id",
    "incident_id",
    "contact_id",
    "contact_name",
    "role",
    "incident_date",
    "severity",
    "relevance",
    "due_by",
    "reason",
    "priority_score",
]


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        if not path.exists() or not path.is_file():
            return None, None
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows: List[Dict[str, str]] = []
            for row in reader:
                # Ensure keys align with header
                rows.append({k: row.get(k, "") for k in header})
            return header, rows
    except Exception:
        return None, None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        if not path.exists() or not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _parse_date_iso(d: str) -> Optional[date]:
    try:
        return date.fromisoformat(d.strip())
    except Exception:
        return None


def _compute_expected(incidents_path: Path, contacts_path: Path) -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    inc_header, inc_rows = _safe_read_csv(incidents_path)
    con_header, con_rows = _safe_read_csv(contacts_path)
    if inc_header is None or inc_rows is None or con_header is None or con_rows is None:
        return None

    # Build allowed contacts by role with allowed_followup == "yes"
    sponsors: List[Dict[str, Any]] = []
    moderators: List[Dict[str, Any]] = []
    for c in con_rows:
        role = c.get("role", "")
        allowed = c.get("allowed_followup", "")
        rel = _parse_int(c.get("relevance", ""))
        if rel is None:
            return None
        c_entry = {
            "contact_id": c.get("contact_id", ""),
            "name": c.get("name", ""),
            "role": role,
            "relevance": rel,
            "allowed_followup": allowed,
        }
        if allowed == "yes":
            if role == "Sponsor":
                sponsors.append(c_entry)
            elif role == "Moderator":
                moderators.append(c_entry)

    reminders: List[Dict[str, Any]] = []
    for inc in inc_rows:
        status = inc.get("status", "")
        sev = _parse_int(inc.get("severity", ""))
        if sev is None:
            return None
        category = inc.get("category", "")
        if status != "open" or sev < 3:
            continue
        incident_id = inc.get("incident_id", "")
        topic = inc.get("topic", "")
        date_str = inc.get("date", "")
        d = _parse_date_iso(date_str)
        if d is None:
            return None
        due = d + timedelta(days=3)
        due_str = due.isoformat()
        if category == "content":
            target_contacts = sponsors
        elif category == "moderation":
            target_contacts = moderators
        else:
            target_contacts = []

        for c in target_contacts:
            priority = sev * 10 + c["relevance"]
            reminder = {
                "reminder_id": f"R-{incident_id}-{c['contact_id']}",
                "incident_id": incident_id,
                "contact_id": c["contact_id"],
                "contact_name": c["name"],
                "role": c["role"],
                "incident_date": d.isoformat(),
                "severity": sev,
                "relevance": c["relevance"],
                "due_by": due_str,
                "reason": f"Open incident on topic: {topic}",
                "priority_score": priority,
            }
            reminders.append(reminder)

    # Sort: priority_score desc, due_by asc, reminder_id asc
    reminders.sort(key=lambda r: (-r["priority_score"], r["due_by"], r["reminder_id"]))

    # Build expected summary
    by_role: Dict[str, int] = {}
    for r in reminders:
        by_role[r["role"]] = by_role.get(r["role"], 0) + 1
    top_5 = [{"reminder_id": r["reminder_id"], "priority_score": r["priority_score"]} for r in reminders[:5]]
    summary = {
        "total_reminders": len(reminders),
        "by_role": by_role,
        "top_5": top_5,
    }
    return reminders, summary


def _csv_rows_to_ordered_lists(rows: List[Dict[str, str]], fields: List[str]) -> Optional[List[List[str]]]:
    ordered: List[List[str]] = []
    try:
        for r in rows:
            ordered.append([r.get(f, "") for f in fields])
        return ordered
    except Exception:
        return None


def _expected_rows_as_strings(reminders: List[Dict[str, Any]]) -> List[List[str]]:
    out: List[List[str]] = []
    for r in reminders:
        row = [
            r["reminder_id"],
            r["incident_id"],
            r["contact_id"],
            r["contact_name"],
            r["role"],
            r["incident_date"],
            str(int(r["severity"])),
            str(int(r["relevance"])),
            r["due_by"],
            r["reason"],
            str(int(r["priority_score"])),
        ]
        out.append(row)
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "reminders_header_correct": 0.0,
        "reminders_row_count_correct": 0.0,
        "reminders_content_order_correct": 0.0,
        "summary_structure_correct": 0.0,
        "summary_consistent_with_csv": 0.0,
        "summary_values_correct": 0.0,
    }

    # Paths
    inc_path = workspace / "input" / "incidents.csv"
    con_path = workspace / "input" / "contacts.csv"
    reminders_path = workspace / "output" / "reminders.csv"
    summary_path = workspace / "output" / "summary.json"

    # Compute expected from inputs
    expected_data = _compute_expected(inc_path, con_path)
    expected_available = expected_data is not None
    if expected_available:
        expected_reminders, expected_summary = expected_data
        expected_rows_str = _expected_rows_as_strings(expected_reminders)
    else:
        expected_reminders, expected_summary, expected_rows_str = None, None, None  # type: ignore

    # Read actual reminders.csv
    actual_header, actual_rows = _safe_read_csv(reminders_path)

    # Check reminders header
    if actual_header is not None and actual_rows is not None:
        if actual_header == EXPECTED_FIELDS:
            scores["reminders_header_correct"] = 1.0
        else:
            scores["reminders_header_correct"] = 0.0

    # Row count check
    if expected_available and actual_rows is not None:
        if len(actual_rows) == len(expected_rows_str):  # type: ignore
            scores["reminders_row_count_correct"] = 1.0
        else:
            scores["reminders_row_count_correct"] = 0.0

    # Content and order check
    if expected_available and actual_header == EXPECTED_FIELDS and actual_rows is not None:
        actual_ordered = _csv_rows_to_ordered_lists(actual_rows, EXPECTED_FIELDS)
        if actual_ordered is not None and actual_ordered == expected_rows_str:  # type: ignore
            scores["reminders_content_order_correct"] = 1.0
        else:
            scores["reminders_content_order_correct"] = 0.0

    # Summary structure check
    summary_obj = _safe_load_json(summary_path)
    if isinstance(summary_obj, dict):
        keys = set(summary_obj.keys())
        required_keys = {"total_reminders", "by_role", "top_5"}
        if keys == required_keys:
            tr = summary_obj.get("total_reminders")
            br = summary_obj.get("by_role")
            t5 = summary_obj.get("top_5")
            types_ok = isinstance(tr, int) and isinstance(br, dict) and isinstance(t5, list)
            # Verify by_role values are ints
            if types_ok:
                roles_types_ok = all(isinstance(k, str) and isinstance(v, int) for k, v in br.items())
                # Verify top_5 item shapes
                top5_types_ok = True
                if len(t5) <= 5:
                    for item in t5:
                        if not isinstance(item, dict):
                            top5_types_ok = False
                            break
                        if set(item.keys()) != {"reminder_id", "priority_score"}:
                            top5_types_ok = False
                            break
                        if not isinstance(item.get("reminder_id"), str) or not isinstance(item.get("priority_score"), int):
                            top5_types_ok = False
                            break
                else:
                    top5_types_ok = False
                if roles_types_ok and top5_types_ok:
                    scores["summary_structure_correct"] = 1.0

    # Summary consistency with CSV
    if summary_obj and actual_header == EXPECTED_FIELDS and actual_rows is not None:
        try:
            # total
            total = len(actual_rows)
            # by_role
            by_role: Dict[str, int] = {}
            for r in actual_rows:
                role = r.get("role", "")
                by_role[role] = by_role.get(role, 0) + 1
            # top_5 from the first five rows
            top_5_actual: List[Dict[str, Any]] = []
            for r in actual_rows[:5]:
                ps = _parse_int(r.get("priority_score", ""))
                rid = r.get("reminder_id", "")
                if ps is None or not isinstance(rid, str):
                    raise ValueError("Invalid priority_score or reminder_id in CSV.")
                top_5_actual.append({"reminder_id": rid, "priority_score": ps})
            if (
                isinstance(summary_obj.get("total_reminders"), int)
                and summary_obj.get("total_reminders") == total
                and isinstance(summary_obj.get("by_role"), dict)
                and summary_obj.get("by_role") == by_role
                and isinstance(summary_obj.get("top_5"), list)
                and summary_obj.get("top_5") == top_5_actual
            ):
                scores["summary_consistent_with_csv"] = 1.0
        except Exception:
            scores["summary_consistent_with_csv"] = 0.0

    # Summary values correct against inputs
    if expected_available and isinstance(summary_obj, dict):
        try:
            if (
                summary_obj.get("total_reminders") == expected_summary["total_reminders"]  # type: ignore
                and summary_obj.get("by_role") == expected_summary["by_role"]  # type: ignore
                and summary_obj.get("top_5") == expected_summary["top_5"]  # type: ignore
            ):
                scores["summary_values_correct"] = 1.0
        except Exception:
            scores["summary_values_correct"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()