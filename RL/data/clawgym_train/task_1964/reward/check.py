import json
import csv
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_yaml_rules(path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    rules: List[Dict[str, Any]] = []
    in_rules = False
    current: Optional[Dict[str, Any]] = None
    try:
        for raw_line in text.splitlines():
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("rules:"):
                in_rules = True
                continue
            if not in_rules:
                continue
            # Detect new rule
            if stripped.startswith("- "):
                if current:
                    rules.append(current)
                current = {}
                # Handle inline "- name: value" form
                after_dash = stripped[2:].strip()
                if after_dash:
                    if ":" in after_dash:
                        key, val = after_dash.split(":", 1)
                        key = key.strip()
                        val = val.strip()
                        if val.startswith('"') and val.endswith('"'):
                            val = val[1:-1]
                        if val.startswith("'") and val.endswith("'"):
                            val = val[1:-1]
                        if key == "offset_days":
                            try:
                                current[key] = int(val)
                            except Exception:
                                return None
                        else:
                            current[key] = val
                continue
            # Parse key: value lines within a rule
            if current is not None and ":" in stripped:
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                if val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                if key == "offset_days":
                    try:
                        current[key] = int(val)
                    except Exception:
                        return None
                else:
                    current[key] = val
        if current:
            rules.append(current)
    except Exception:
        return None

    # Validate parsed rules
    required_keys = {"name", "trigger", "offset_days", "assignee", "channel"}
    for r in rules:
        if not required_keys.issubset(r.keys()):
            return None
    return rules


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _date_to_str(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _is_weekend(d: datetime) -> bool:
    # Monday=0, Sunday=6
    return d.weekday() >= 5


def _adjust_to_weekday(d: datetime) -> Tuple[datetime, Optional[datetime]]:
    if not _is_weekend(d):
        return d, None
    # Shift to next Monday
    # If Saturday (5): +2 days, if Sunday (6): +1 day
    delta = 7 - d.weekday()
    # For Saturday: weekday=5 -> 7-5=2; Sunday: 6 -> 7-6=1
    adjusted = d + timedelta(days=delta)
    return adjusted, d


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Normalize keys and strip values
                norm = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows.append(norm)
            return rows
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _sanitize_heading(line: str) -> str:
    s = line.strip()
    # Remove leading markdown heading markers
    s = re.sub(r"^\s*#+\s*", "", s)
    return s.strip()


def _find_section_ranges(lines: List[str], titles: List[str]) -> Optional[Dict[str, Tuple[int, int]]]:
    # Find indices of headings matching titles in order
    title_indices = {}
    normalized_titles = [t.strip() for t in titles]
    indices = []
    for t in normalized_titles:
        found_idx = None
        for i, line in enumerate(lines):
            if i in [idx for (_, idx) in indices]:
                continue
            head = _sanitize_heading(line)
            if head == t:
                # Ensure strictly increasing indices
                if indices and i <= indices[-1][1]:
                    continue
                found_idx = i
                indices.append((t, i))
                break
        if found_idx is None:
            return None
    # Determine section ranges: from heading line to next heading line
    ranges: Dict[str, Tuple[int, int]] = {}
    for idx, (t, i) in enumerate(indices):
        start = i
        end = len(lines)
        if idx + 1 < len(indices):
            end = indices[idx + 1][1]
        ranges[t] = (start, end)
    return ranges


def _extract_bullets(section_lines: List[str]) -> List[str]:
    bullets = []
    for line in section_lines:
        stripped = line.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets.append(stripped.strip())
    return bullets


def _compute_expected(schedule_rows: List[Dict[str, str]], rules: List[Dict[str, Any]], feedback_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Prepare schedule lookup
    spreads = []
    for row in schedule_rows:
        spreads.append({
            "spread_id": row.get("spread_id", ""),
            "article_title": row.get("article_title", ""),
            "events": {k: v for k, v in row.items() if k not in ("spread_id", "article_title")}
        })

    spread_ids_set = set(s["spread_id"] for s in spreads if s["spread_id"])

    # Compute reminders
    reminders = []
    skipped: Dict[str, List[str]] = {}
    adjusted_entries: List[Dict[str, str]] = []

    # Determine all event columns present in CSV (excluding first two)
    event_columns = []
    if schedule_rows:
        for k in schedule_rows[0].keys():
            if k not in ("spread_id", "article_title"):
                event_columns.append(k)

    for rule in rules:
        rule_name = rule["name"]
        trigger = rule["trigger"]
        offset = int(rule["offset_days"])
        assignee = rule["assignee"]
        channel = rule["channel"]
        # Initialize skipped list
        skipped.setdefault(rule_name, [])
        for s in spreads:
            tr_date_str = s["events"].get(trigger, "")
            if not tr_date_str:
                skipped[rule_name].append(s["spread_id"])
                continue
            tr_date = _parse_date(tr_date_str)
            if not tr_date:
                skipped[rule_name].append(s["spread_id"])
                continue
            due = tr_date + timedelta(days=offset)
            adjusted, original_if_adjusted = _adjust_to_weekday(due)
            due_str = _date_to_str(adjusted)
            reminders.append({
                "spread_id": s["spread_id"],
                "article_title": s["article_title"],
                "reminder_name": rule_name,
                "assignee": assignee,
                "channel": channel,
                "source_event": trigger,
                "trigger_date": tr_date_str,
                "due_date": due_str,
            })
            if original_if_adjusted is not None:
                adjusted_entries.append({
                    "spread_id": s["spread_id"],
                    "reminder_name": rule_name,
                    "original_due_date": _date_to_str(original_if_adjusted),
                    "adjusted_due_date": due_str
                })

    # Compute meeting_date: one day after the latest non-empty event date across all event columns
    latest_date: Optional[datetime] = None
    for row in schedule_rows:
        for col in event_columns:
            val = row.get(col, "")
            if val:
                d = _parse_date(val)
                if d and (latest_date is None or d > latest_date):
                    latest_date = d
    meeting_date = None
    if latest_date is not None:
        meeting_date = _date_to_str(latest_date + timedelta(days=1))

    # Compute unknown_spread_ids_in_feedback
    unknown_spread_ids = []
    for item in feedback_items:
        sid = item.get("spread_id")
        if sid and sid not in spread_ids_set and sid not in unknown_spread_ids:
            unknown_spread_ids.append(sid)

    # Compute parent priorities: spreads with at least one open Parent (Pat) feedback, most recent such
    parent_priorities = {}
    for item in feedback_items:
        try:
            if item.get("status") != "open":
                continue
            if item.get("from") != "Parent (Pat)":
                continue
            sid = item.get("spread_id")
            if not sid:
                continue
            d = _parse_date(item.get("date", ""))
            if not d:
                continue
            key = sid
            cur = parent_priorities.get(key)
            if cur is None or _parse_date(cur["date"]) < d:
                parent_priorities[key] = {
                    "spread_id": sid,
                    "date": item.get("date"),
                    "summary": item.get("summary", ""),
                    "from": item.get("from")
                }
        except Exception:
            continue

    # Map spread_id -> article_title from schedule
    sid_to_title = {s["spread_id"]: s["article_title"] for s in spreads}

    # Compute open feedback latest per spread
    latest_open_per_spread = {}
    for item in feedback_items:
        try:
            if item.get("status") != "open":
                continue
            sid = item.get("spread_id")
            if not sid:
                continue
            d = _parse_date(item.get("date", ""))
            if not d:
                continue
            cur = latest_open_per_spread.get(sid)
            if cur is None or _parse_date(cur["date"]) < d:
                latest_open_per_spread[sid] = {
                    "spread_id": sid,
                    "date": item.get("date"),
                    "summary": item.get("summary", ""),
                    "from": item.get("from")
                }
        except Exception:
            continue

    # Attach titles
    for entry in parent_priorities.values():
        entry["article_title"] = sid_to_title.get(entry["spread_id"], "")
    for entry in latest_open_per_spread.values():
        entry["article_title"] = sid_to_title.get(entry["spread_id"], "")

    expected = {
        "reminders": reminders,
        "skipped_missing_event_dates": skipped,
        "due_dates_adjusted_to_weekday": adjusted_entries,
        "meeting_date": meeting_date,
        "unknown_spread_ids_in_feedback": unknown_spread_ids,
        "parent_priorities": parent_priorities,
        "latest_open_per_spread": latest_open_per_spread,
    }
    return expected


def _canonical_reminder_tuple(d: Dict[str, str]) -> Tuple[str, str, str, str, str, str, str, str]:
    return (
        d.get("spread_id", ""),
        d.get("article_title", ""),
        d.get("reminder_name", ""),
        d.get("assignee", ""),
        d.get("channel", ""),
        d.get("source_event", ""),
        d.get("trigger_date", ""),
        d.get("due_date", ""),
    )


def _lines_after_heading(lines: List[str], start: int, end: int) -> List[str]:
    # Remove the heading line itself
    return lines[start + 1:end]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "reminders_csv_columns_correct": 0.0,
        "reminders_csv_content_correct": 0.0,
        "meeting_notes_sections_order_correct": 0.0,
        "meeting_notes_parent_priorities_content": 0.0,
        "meeting_notes_action_items_content": 0.0,
        "meeting_notes_action_items_sorted": 0.0,
        "meeting_notes_open_feedback_content": 0.0,
        "consistency_report_fields_present": 0.0,
        "consistency_report_values_correct": 0.0,
    }

    # Load inputs
    yaml_path = workspace / "input" / "reminder_config.yaml"
    schedule_path = workspace / "input" / "issue_schedule.csv"
    feedback_path = workspace / "input" / "layout_feedback.jsonl"

    rules = _load_yaml_rules(yaml_path)
    schedule_rows = _load_csv_dicts(schedule_path)
    feedback_items = _load_jsonl(feedback_path)

    if rules is None or schedule_rows is None or feedback_items is None:
        # Without inputs we cannot compute expectations; all checks remain 0.0
        return scores

    expected = _compute_expected(schedule_rows, rules, feedback_items)

    # Load outputs
    reminders_csv_path = workspace / "out" / "reminders.csv"
    meeting_notes_path = workspace / "out" / "meeting_notes.md"
    report_json_path = workspace / "out" / "consistency_report.json"

    # Check reminders.csv
    actual_reminders: Optional[List[Dict[str, str]]] = None
    try:
        if reminders_csv_path.exists():
            with reminders_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                actual_reminders = []
                for row in reader:
                    actual_reminders.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            # Columns check
            required_cols = ["spread_id", "article_title", "reminder_name", "assignee", "channel", "source_event", "trigger_date", "due_date"]
            if actual_reminders is not None and len(actual_reminders) >= 0:
                # DictReader fieldnames
                with reminders_csv_path.open("r", encoding="utf-8", newline="") as fcols:
                    reader2 = csv.reader(fcols)
                    header = next(reader2, [])
                if header == required_cols:
                    scores["reminders_csv_columns_correct"] = 1.0
        else:
            actual_reminders = None
    except Exception:
        actual_reminders = None

    # Content correctness for reminders.csv
    try:
        if actual_reminders is not None:
            expected_set = set(_canonical_reminder_tuple(r) for r in expected["reminders"])
            actual_set = set(_canonical_reminder_tuple(r) for r in actual_reminders)
            if expected_set == actual_set and len(actual_reminders) == len(expected["reminders"]):
                scores["reminders_csv_content_correct"] = 1.0
    except Exception:
        pass

    # Parse meeting notes
    meeting_lines: Optional[List[str]] = None
    if meeting_notes_path.exists():
        try:
            text = meeting_notes_path.read_text(encoding="utf-8")
            meeting_lines = text.splitlines()
        except Exception:
            meeting_lines = None

    # Check meeting notes sections order
    titles = [
        "Parent priorities",
        "Action Items (rule-based reminders)",
        "Open Feedback (latest per spread)",
    ]
    section_ranges = None
    if meeting_lines is not None:
        try:
            section_ranges = _find_section_ranges(meeting_lines, titles)
            if section_ranges is not None:
                scores["meeting_notes_sections_order_correct"] = 1.0
        except Exception:
            section_ranges = None

    # Meeting notes parent priorities content
    try:
        if section_ranges is not None and meeting_lines is not None:
            start, end = section_ranges[titles[0]]
            section_text = _lines_after_heading(meeting_lines, start, end)
            bullets = _extract_bullets(section_text)
            # Expected parent priorities
            expected_pp = expected["parent_priorities"]
            # Build expectations with titles
            sid_to_title = {row["spread_id"]: row["article_title"] for row in schedule_rows}
            # We expect exactly one bullet per spread with open parent feedback
            if len(bullets) == len(expected_pp):
                # Check each expected item appears as required
                meeting_date = expected["meeting_date"]
                all_ok = True
                for sid, entry in expected_pp.items():
                    title = sid_to_title.get(sid, "")
                    summary = entry.get("summary", "")
                    found = False
                    for b in bullets:
                        if "[PARENT]" in b and sid in b and title in b and summary in b and (meeting_date in b if meeting_date else True):
                            found = True
                            break
                    if not found:
                        all_ok = False
                        break
                if all_ok:
                    scores["meeting_notes_parent_priorities_content"] = 1.0
    except Exception:
        pass

    # Meeting notes action items content and sorted
    try:
        if section_ranges is not None and meeting_lines is not None and actual_reminders is not None:
            start, end = section_ranges[titles[1]]
            bullets = _extract_bullets(_lines_after_heading(meeting_lines, start, end))
            # Must have exactly as many bullets as reminders
            if len(bullets) == len(expected["reminders"]):
                # For each expected reminder, ensure a bullet contains required fields
                all_present = True
                for r in expected["reminders"]:
                    components = [
                        r["spread_id"],
                        r["article_title"],
                        r["reminder_name"],
                        r["assignee"],
                        r["channel"],
                        r["source_event"],
                        r["due_date"],
                    ]
                    # Find a bullet that contains all components
                    matched = False
                    for b in bullets:
                        if all(str(c) in b for c in components):
                            matched = True
                            break
                    if not matched:
                        all_present = False
                        break
                if all_present:
                    scores["meeting_notes_action_items_content"] = 1.0

                # Check sorted by due_date then spread_id
                # Extract (due_date, spread_id) per bullet
                # Known spread_ids
                known_spreads = {row["spread_id"] for row in schedule_rows}
                extracted_pairs: List[Tuple[str, str]] = []
                date_pattern = re.compile(r"\d{4}-\d{2}-\d{2}")
                for b in bullets:
                    # Find date
                    m = date_pattern.search(b)
                    due = m.group(0) if m else ""
                    # Find spread id
                    sid_found = None
                    for sid in known_spreads:
                        if sid in b:
                            sid_found = sid
                            break
                    extracted_pairs.append((due, sid_found if sid_found else ""))

                # Validate nondecreasing sort
                is_sorted = True
                for i in range(1, len(extracted_pairs)):
                    prev = extracted_pairs[i - 1]
                    curr = extracted_pairs[i]
                    if prev[0] > curr[0]:
                        is_sorted = False
                        break
                    if prev[0] == curr[0] and prev[1] > curr[1]:
                        is_sorted = False
                        break
                if is_sorted:
                    scores["meeting_notes_action_items_sorted"] = 1.0
    except Exception:
        pass

    # Meeting notes open feedback content
    try:
        if section_ranges is not None and meeting_lines is not None:
            start, end = section_ranges[titles[2]]
            bullets = _extract_bullets(_lines_after_heading(meeting_lines, start, end))
            expected_latest = expected["latest_open_per_spread"]
            # Only include spreads that have any open feedback
            expected_count = len(expected_latest)
            if len(bullets) == expected_count:
                all_ok = True
                sid_to_title = {row["spread_id"]: row["article_title"] for row in schedule_rows}
                for sid, entry in expected_latest.items():
                    title = sid_to_title.get(sid, "")
                    from_str = entry.get("from", "")
                    date_str = entry.get("date", "")
                    summary = entry.get("summary", "")
                    # If latest is from Parent (Pat), [PARENT] must be present
                    need_parent_flag = (from_str == "Parent (Pat)")
                    found = False
                    for b in bullets:
                        cond = (sid in b and title in b and from_str in b and date_str in b and summary in b)
                        if need_parent_flag:
                            cond = cond and ("[PARENT]" in b)
                        if cond:
                            found = True
                            break
                    if not found:
                        all_ok = False
                        break
                if all_ok:
                    scores["meeting_notes_open_feedback_content"] = 1.0
    except Exception:
        pass

    # Consistency report
    report_obj: Optional[Dict[str, Any]] = None
    if report_json_path.exists():
        try:
            report_obj = json.loads(report_json_path.read_text(encoding="utf-8"))
        except Exception:
            report_obj = None

    if report_obj is not None:
        # Fields present
        required_fields = [
            "meeting_date",
            "total_reminders",
            "skipped_missing_event_dates",
            "due_dates_adjusted_to_weekday",
            "unknown_spread_ids_in_feedback",
        ]
        if all(k in report_obj for k in required_fields):
            scores["consistency_report_fields_present"] = 1.0

        # Values correct
        try:
            values_ok = True
            # meeting_date
            if report_obj.get("meeting_date") != expected["meeting_date"]:
                values_ok = False
            # total_reminders
            if report_obj.get("total_reminders") != len(expected["reminders"]):
                values_ok = False
            # skipped_missing_event_dates
            rep_skipped = report_obj.get("skipped_missing_event_dates")
            if isinstance(rep_skipped, dict):
                # Compare keys and sets of lists
                exp_skipped = expected["skipped_missing_event_dates"]
                if set(rep_skipped.keys()) != set(exp_skipped.keys()):
                    values_ok = False
                else:
                    for k in exp_skipped.keys():
                        # Order not enforced; compare as sets
                        if set(rep_skipped.get(k, [])) != set(exp_skipped.get(k, [])):
                            values_ok = False
                            break
            else:
                values_ok = False
            # due_dates_adjusted_to_weekday
            rep_adjusted = report_obj.get("due_dates_adjusted_to_weekday")
            exp_adjusted = expected["due_dates_adjusted_to_weekday"]
            if not isinstance(rep_adjusted, list):
                values_ok = False
            else:
                # Compare as sets of tuples for stability
                def canon_adj(lst):
                    can = set()
                    for e in lst:
                        try:
                            can.add((e.get("spread_id"), e.get("reminder_name"), e.get("original_due_date"), e.get("adjusted_due_date")))
                        except Exception:
                            return None
                    return can
                rep_can = canon_adj(rep_adjusted)
                exp_can = canon_adj(exp_adjusted)
                if rep_can is None or exp_can is None or rep_can != exp_can:
                    values_ok = False
            # unknown_spread_ids_in_feedback
            rep_unknown = report_obj.get("unknown_spread_ids_in_feedback")
            if set(rep_unknown) != set(expected["unknown_spread_ids_in_feedback"]):
                values_ok = False

            if values_ok:
                scores["consistency_report_values_correct"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()