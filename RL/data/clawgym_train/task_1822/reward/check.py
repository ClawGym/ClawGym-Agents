import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _float_eq(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _compute_expected_metrics(workspace: Path) -> Optional[Dict[str, Any]]:
    events_path = workspace / "input" / "events.csv"
    signins_path = workspace / "input" / "signins.csv"
    events = _parse_csv(events_path)
    signins = _parse_csv(signins_path)
    if events is None or signins is None:
        return None

    start = _parse_date("2026-04-08")
    end = _parse_date("2026-04-12")
    if start is None or end is None:
        return None

    # Filter events by date range
    filtered_events = []
    for r in events:
        d = _parse_date(r.get("date", ""))
        if d is None:
            return None
        if start <= d <= end:
            filtered_events.append(r)

    # Compute event metrics
    total_events = len(filtered_events)
    attendance_by_neighborhood: Dict[str, int] = {}
    events_by_type: Dict[str, int] = {}
    total_attendance = 0
    event_ids_in_range = set()
    for r in filtered_events:
        event_ids_in_range.add(r.get("id", "").strip())
        try:
            attendees = int(str(r.get("attendees_estimate", "0")).strip())
        except Exception:
            return None
        total_attendance += attendees
        neighborhood = str(r.get("neighborhood", "")).strip()
        attendance_by_neighborhood[neighborhood] = attendance_by_neighborhood.get(neighborhood, 0) + attendees
        event_type = str(r.get("event_type", "")).strip()
        events_by_type[event_type] = events_by_type.get(event_type, 0) + 1

    # Compute volunteer metrics from sign-ins filtered by event_id
    total_volunteer_hours = 0.0
    unique_volunteers: set = set()
    for r in signins:
        event_id = str(r.get("event_id", "")).strip()
        if event_id in event_ids_in_range:
            try:
                hours = float(str(r.get("hours", "0")).strip())
            except Exception:
                return None
            total_volunteer_hours += hours
            unique_volunteers.add(str(r.get("volunteer_id", "")).strip())

    expected = {
        "total_events": total_events,
        "total_attendance": total_attendance,
        "attendance_by_neighborhood": dict(sorted(attendance_by_neighborhood.items())),
        "events_by_type": dict(sorted(events_by_type.items())),
        "total_volunteer_hours": float(total_volunteer_hours),
        "unique_volunteers": len(unique_volunteers),
    }
    return expected


def _extract_decisions_actions_from_transcript(workspace: Path) -> Optional[Tuple[List[str], List[Dict[str, Any]]]]:
    transcript_path = workspace / "input" / "meeting_transcript.txt"
    content = _read_text(transcript_path)
    if content is None:
        return None

    decisions: List[str] = []
    actions: List[Dict[str, Any]] = []

    lines = content.splitlines()
    for raw in lines:
        line = raw.strip()
        if line.startswith("DECISION:"):
            decisions.append(line[len("DECISION:"):].strip())
        elif line.startswith("ACTION:"):
            body = line[len("ACTION:"):].strip()
            # Find due date as last YYYY-MM-DD in the line
            due_matches = list(re.finditer(r"\b(\d{4}-\d{2}-\d{2})\b", body))
            if not due_matches:
                # Malformed action; fail extraction robustly
                return None
            due_date = due_matches[-1].group(1)
            # Remove trailing period after date if present
            # Determine indices for parsing assignee and description
            # Expect "Assignee to <description> by YYYY-MM-DD"
            # Find the ' to ' occurrence before the due date
            # We search from start
            to_idx = body.lower().find(" to ")
            by_idx = body.lower().rfind(" by ")
            if to_idx == -1 or by_idx == -1 or to_idx >= by_idx:
                return None
            assignee = body[:to_idx].strip().rstrip(".")
            description = body[to_idx + 4:by_idx].strip().rstrip(".")
            # Basic validation
            if not assignee or not description:
                return None
            actions.append({
                "assignee": assignee,
                "description": description,
                "due_date": due_date
            })

    # Sort actions by due_date ascending
    try:
        actions.sort(key=lambda a: _parse_date(a["due_date"]))
    except Exception:
        return None

    return decisions, actions


def _load_metrics_json(workspace: Path) -> Optional[Dict[str, Any]]:
    mp = workspace / "output" / "metrics.json"
    return _load_json(mp)


def _check_line_contains_both(text: str, a: str, b: str) -> bool:
    for ln in text.splitlines():
        if a in ln and b in ln:
            return True
    return False


def _find_first_paragraph(text: str) -> str:
    # Return the first paragraph (block of non-empty lines)
    lines = text.splitlines()
    para_lines = []
    for ln in lines:
        if ln.strip() == "":
            if para_lines:
                break
            else:
                continue
        para_lines.append(ln.rstrip())
    return " ".join(para_lines).strip()


def _split_sentences(text: str) -> List[str]:
    # Simple sentence split by . ! ?
    parts = re.split(r'[.!?]+', text)
    return [s.strip() for s in parts if s.strip()]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "metrics_json_exists_and_valid": 0.0,
        "metrics_values_correct": 0.0,
        "meeting_notes_decisions_included": 0.0,
        "meeting_notes_actions_extracted_and_sorted": 0.0,
        "weekly_update_overview_date_range": 0.0,
        "weekly_update_metrics_match_json": 0.0,
        "weekly_update_highlights_verbatim": 0.0,
        "weekly_update_upcoming_actions_summary": 0.0,
        "volunteer_email_subject_line": 0.0,
        "volunteer_email_opening_equity_access": 0.0,
        "volunteer_email_references_metric_numbers": 0.0,
        "volunteer_email_action_items_bulleted_top_three": 0.0,
        "volunteer_email_clear_call_to_action": 0.0,
    }

    # Compute expected metrics from inputs
    expected_metrics = _compute_expected_metrics(workspace)

    # Load metrics.json
    metrics_path = workspace / "output" / "metrics.json"
    metrics_json = _load_metrics_json(workspace)
    if metrics_json is not None and isinstance(metrics_json, dict):
        required_keys = [
            "total_events",
            "total_attendance",
            "attendance_by_neighborhood",
            "events_by_type",
            "total_volunteer_hours",
            "unique_volunteers",
        ]
        has_all = all(k in metrics_json for k in required_keys)
        types_ok = (
            isinstance(metrics_json.get("total_events"), int)
            and isinstance(metrics_json.get("total_attendance"), int)
            and isinstance(metrics_json.get("attendance_by_neighborhood"), dict)
            and isinstance(metrics_json.get("events_by_type"), dict)
            and isinstance(metrics_json.get("total_volunteer_hours"), (int, float))
            and isinstance(metrics_json.get("unique_volunteers"), int)
        )
        if has_all and types_ok:
            scores["metrics_json_exists_and_valid"] = 1.0

    # Compare metrics values if we have both
    if expected_metrics is not None and metrics_json is not None:
        try:
            ok = True
            ok = ok and (metrics_json.get("total_events") == expected_metrics["total_events"])
            ok = ok and (metrics_json.get("total_attendance") == expected_metrics["total_attendance"])
            # Strict equality on dicts: same keys and values
            def dicts_equal_strict(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
                if set(a.keys()) != set(b.keys()):
                    return False
                for k in a:
                    if a[k] != b[k]:
                        return False
                return True
            ok = ok and dicts_equal_strict(metrics_json.get("attendance_by_neighborhood", {}), expected_metrics["attendance_by_neighborhood"])
            ok = ok and dicts_equal_strict(metrics_json.get("events_by_type", {}), expected_metrics["events_by_type"])
            # floats
            ok = ok and _float_eq(float(metrics_json.get("total_volunteer_hours")), float(expected_metrics["total_volunteer_hours"]))
            ok = ok and (metrics_json.get("unique_volunteers") == expected_metrics["unique_volunteers"])
            scores["metrics_values_correct"] = 1.0 if ok else 0.0
        except Exception:
            scores["metrics_values_correct"] = 0.0

    # Meeting notes checks
    meeting_notes_path = workspace / "output" / "meeting_notes.md"
    meeting_notes = _read_text(meeting_notes_path)
    transcript_parsed = _extract_decisions_actions_from_transcript(workspace)

    if meeting_notes is not None and transcript_parsed is not None:
        decisions_expected, actions_expected = transcript_parsed
        # Decisions included
        try:
            decisions_ok = all(d in meeting_notes for d in decisions_expected) and len(decisions_expected) > 0
        except Exception:
            decisions_ok = False
        scores["meeting_notes_decisions_included"] = 1.0 if decisions_ok else 0.0

        # Actions extracted with fields and sorted by due_date
        try:
            # For each expected action, check presence of assignee, description, and due_date in meeting_notes
            all_present = True
            positions = []
            for a in actions_expected:
                assignee = a["assignee"]
                desc = a["description"]
                due = a["due_date"]
                # Check presence
                present = (assignee in meeting_notes) and (desc in meeting_notes) and (due in meeting_notes)
                if not present:
                    all_present = False
                # Find a position marker using due date (unique)
                idx = meeting_notes.find(due)
                if idx == -1:
                    all_present = False
                positions.append((due, idx))
            # Check sorted ascending by due_date -> positions must be increasing by date order
            # We know actions_expected already sorted by due_date ascending; verify their indices in this order increasing
            sorted_by_due_positions = [pos for (_, pos) in positions]
            order_ok = True
            if len(sorted_by_due_positions) >= 2:
                last = -1
                for p in sorted_by_due_positions:
                    if p < last:
                        order_ok = False
                        break
                    last = p
            actions_ok = all_present and order_ok and len(actions_expected) > 0
        except Exception:
            actions_ok = False
        scores["meeting_notes_actions_extracted_and_sorted"] = 1.0 if actions_ok else 0.0

    # Weekly update checks
    weekly_update_path = workspace / "output" / "weekly_update.md"
    weekly_update = _read_text(weekly_update_path)
    if weekly_update is not None:
        # Overview must state date range
        if "2026-04-08 to 2026-04-12" in weekly_update:
            scores["weekly_update_overview_date_range"] = 1.0

        # Highlights verbatim
        highlights_path = workspace / "input" / "highlights.md"
        highlights = _read_text(highlights_path)
        if highlights is not None:
            try:
                hl_ok = True
                for ln in highlights.splitlines():
                    if ln.strip() == "":
                        continue
                    # Require exact line presence
                    if ln not in weekly_update:
                        hl_ok = False
                        break
                scores["weekly_update_highlights_verbatim"] = 1.0 if hl_ok else 0.0
            except Exception:
                scores["weekly_update_highlights_verbatim"] = 0.0

        # Key Metrics match metrics.json
        mj = metrics_json
        metrics_ok = False
        if mj is not None and isinstance(mj, dict):
            try:
                # Scalars exact string presence
                scalars_ok = True
                scalar_values = {
                    "total_events": mj.get("total_events"),
                    "total_attendance": mj.get("total_attendance"),
                    "total_volunteer_hours": mj.get("total_volunteer_hours"),
                    "unique_volunteers": mj.get("unique_volunteers"),
                }
                # Convert to canonical strings
                scalar_strs = {k: (str(int(v)) if isinstance(v, bool) is False and isinstance(v, float) and v.is_integer() else str(v)) for k, v in scalar_values.items()}
                # But for ints, str is fine; for float: str(v)
                # Ensure presence of exact numeric strings
                for k, v in scalar_values.items():
                    s = str(v)
                    if s not in weekly_update:
                        scalars_ok = False
                        break
                # Attendance by neighborhood breakdown lines
                abn = mj.get("attendance_by_neighborhood", {})
                abn_ok = True
                if not isinstance(abn, dict) or not abn:
                    abn_ok = False
                else:
                    for nbh, val in abn.items():
                        n_ok = _check_line_contains_both(weekly_update, str(nbh), str(val))
                        if not n_ok:
                            abn_ok = False
                            break
                metrics_ok = scalars_ok and abn_ok
            except Exception:
                metrics_ok = False
        scores["weekly_update_metrics_match_json"] = 1.0 if metrics_ok else 0.0

        # Upcoming Action Items summary: first three by earliest due_date, include (description, assignee, due_date) and indicate total count
        transcript_info = _extract_decisions_actions_from_transcript(workspace)
        if transcript_info is not None:
            _, actions_expected_all = transcript_info
            top3 = actions_expected_all[:3] if len(actions_expected_all) >= 3 else actions_expected_all
            try:
                present_all = True
                positions = []
                for a in top3:
                    if (a["description"] in weekly_update) and (a["assignee"] in weekly_update) and (a["due_date"] in weekly_update):
                        positions.append(weekly_update.find(a["due_date"]))
                    else:
                        present_all = False
                order_ok = True
                if len(positions) >= 2:
                    last = -1
                    for p in positions:
                        if p < last:
                            order_ok = False
                            break
                        last = p
                # indicate total count
                total_count = len(actions_expected_all)
                # Look for pattern like "5 action item" near the number
                indicate_ok = False
                # search windows
                for m in re.finditer(str(total_count), weekly_update):
                    start = max(0, m.start() - 50)
                    end = min(len(weekly_update), m.end() + 50)
                    window = weekly_update[start:end].lower()
                    if "action item" in window:
                        indicate_ok = True
                        break
                ua_ok = present_all and order_ok and indicate_ok and len(top3) == 3 and total_count >= 3
            except Exception:
                ua_ok = False
            scores["weekly_update_upcoming_actions_summary"] = 1.0 if ua_ok else 0.0

    # Volunteer email checks
    email_path = workspace / "output" / "volunteer_email.txt"
    email_text = _read_text(email_path)
    if email_text is not None:
        # Subject line includes phrase
        subject_ok = False
        for ln in email_text.splitlines():
            if "Weekly Update: 2026-04-08 to 2026-04-12" in ln:
                subject_ok = True
                break
        scores["volunteer_email_subject_line"] = 1.0 if subject_ok else 0.0

        # Opening paragraph equity and access with 2-3 sentences
        para1 = _find_first_paragraph(email_text)
        sentences = _split_sentences(para1)
        opening_ok = False
        if len(sentences) in (2, 3):
            low = para1.lower()
            if "equity" in low and "access" in low:
                opening_ok = True
        scores["volunteer_email_opening_equity_access"] = 1.0 if opening_ok else 0.0

        # Reference at least two metric numbers from metrics.json
        metrics_num_ok = False
        if metrics_json is not None and isinstance(metrics_json, dict):
            scalar_vals = [
                str(metrics_json.get("total_events")),
                str(metrics_json.get("total_attendance")),
                str(metrics_json.get("total_volunteer_hours")),
                str(metrics_json.get("unique_volunteers")),
            ]
            count_refs = 0
            for s in scalar_vals:
                if s is not None and s in email_text:
                    count_refs += 1
            if count_refs >= 2:
                metrics_num_ok = True
        scores["volunteer_email_references_metric_numbers"] = 1.0 if metrics_num_ok else 0.0

        # Bulleted list of top three upcoming action items by earliest due_date (description and due_date only)
        bullets = [ln for ln in email_text.splitlines() if ln.strip().startswith(("-", "*"))]
        bullets_text = "\n".join(bullets)
        actions_info = _extract_decisions_actions_from_transcript(workspace)
        bulleted_ok = False
        if actions_info is not None:
            _, all_actions = actions_info
            top3 = all_actions[:3] if len(all_actions) >= 3 else all_actions
            try:
                matches = 0
                for a in top3:
                    # Find bullet containing both description and due date
                    found = False
                    for b in bullets:
                        bt = b.strip()
                        if (a["description"] in bt) and (a["due_date"] in bt):
                            # Ensure no assignee appears if "description and due_date only"
                            if a["assignee"] not in bt:
                                found = True
                                break
                    if found:
                        matches += 1
                bulleted_ok = (matches == 3 and len(top3) == 3)
            except Exception:
                bulleted_ok = False
        scores["volunteer_email_action_items_bulleted_top_three"] = 1.0 if bulleted_ok else 0.0

        # Clear, encouraging call to action
        cta_ok = False
        lowered = email_text.lower()
        keywords = ["join", "sign up", "volunteer", "participate", "help", "rsvp", "come", "step up"]
        for kw in keywords:
            if kw in lowered:
                cta_ok = True
                break
        scores["volunteer_email_clear_call_to_action"] = 1.0 if cta_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()