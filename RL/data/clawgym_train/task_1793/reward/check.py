import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_csv_dicts(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
            headers = reader.fieldnames or []
            return rows, headers
    except Exception:
        return None


def parse_simple_yaml_map(path: Path) -> Optional[Dict[str, str]]:
    """
    Minimal parser for simple top-level YAML key: value pairs with optional quotes.
    Ignores comments and blank lines. Does not support nested structures.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    data: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # handle cases where the line might contain colon in a quoted string by splitting only on first colon
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        # remove optional quotes
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        data[key] = value
    return data


def compute_attendance_stats(rows: List[Dict[str, str]]) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Returns (overall_counts, yes_by_role) where overall_counts has keys:
    total_attendees, yes, maybe, no. yes_by_role maps role -> yes_count.
    """
    total = len(rows)
    yes = 0
    maybe = 0
    no = 0
    yes_by_role: Dict[str, int] = {}
    for r in rows:
        rsvp = (r.get("RSVP") or "").strip()
        role = (r.get("role") or "").strip()
        rsvp_lower = rsvp.lower()
        if rsvp_lower == "yes":
            yes += 1
            if role not in yes_by_role:
                yes_by_role[role] = 0
            yes_by_role[role] += 1
        elif rsvp_lower == "maybe":
            maybe += 1
        elif rsvp_lower == "no":
            no += 1
    overall = {
        "total_attendees": total,
        "yes": yes,
        "maybe": maybe,
        "no": no,
    }
    # Ensure all roles present in input are represented in yes_by_role with at least zero
    roles_in_input = set((r.get("role") or "").strip() for r in rows)
    for role in roles_in_input:
        if role not in yes_by_role:
            yes_by_role[role] = 0
    return overall, yes_by_role


def parse_meeting_notes(notes_text: str) -> Dict[str, object]:
    decisions: List[str] = []
    actions: List[Tuple[str, str, str]] = []
    next_meeting = {"date_time": None, "location": None, "purpose": None}
    first_walk_date: Optional[str] = None

    lines = notes_text.splitlines()

    # Extract decisions
    decision_re = re.compile(r'^\s*-\s*Decision:\s*(.+?)\s*$')
    for line in lines:
        m = decision_re.match(line)
        if m:
            decisions.append(m.group(1).strip())

    # Extract first_walk_date from decisions
    for dec in decisions:
        mdate = re.search(r'(\d{4}-\d{2}-\d{2})', dec)
        if mdate and ("first walk" in dec.lower() or "target date" in dec.lower()):
            first_walk_date = mdate.group(1)
            break

    # Extract actions
    # Pattern: - Action: Assignee to Task by YYYY-MM-DD.
    action_re = re.compile(
        r'^\s*-\s*Action:\s*([A-Za-z .-]+?)\s+to\s+(.+?)\s+by\s+(\d{4}-\d{2}-\d{2})\.?\s*$'
    )
    for line in lines:
        ma = action_re.match(line)
        if ma:
            assignee = ma.group(1).strip()
            task = ma.group(2).strip()
            due = ma.group(3).strip()
            actions.append((assignee, task, due))

    # Extract next meeting block
    try:
        idx = next(i for i, l in enumerate(lines) if l.strip().lower().startswith("next meeting"))
        nm_lines = lines[idx + 1 : idx + 5]  # a few lines following
        for l in nm_lines:
            l_stripped = l.strip()
            if l_stripped.lower().startswith("- date:"):
                next_meeting["date_time"] = l_stripped.split(":", 1)[1].strip()
            elif l_stripped.lower().startswith("- location:"):
                next_meeting["location"] = l_stripped.split(":", 1)[1].strip()
            elif l_stripped.lower().startswith("- purpose:"):
                next_meeting["purpose"] = l_stripped.split(":", 1)[1].strip()
    except StopIteration:
        pass

    return {
        "decisions": decisions,
        "actions": actions,
        "next_meeting": next_meeting,
        "first_walk_date": first_walk_date,
    }


def find_section_lines(lines: List[str], header_name: str) -> List[str]:
    """
    Finds lines under a section header matching header_name (case-insensitive),
    where a header line starts with header_name and may have trailing colon or be a markdown header.
    Returns the list of lines below the header until the next header (Decisions, Action Items, Next Meeting)
    or end of file.
    """
    targets = ["decisions", "action items", "next meeting"]
    header_name_l = header_name.lower()
    start_idx = None
    for i, l in enumerate(lines):
        s = l.strip().lower()
        if s.startswith(header_name_l):
            start_idx = i + 1
            break
        # markdown header could be like "## Decisions"
        if s.startswith("#") and s.lstrip("#").strip().startswith(header_name_l):
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    # find end index
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        sj = lines[j].strip().lower()
        if any(
            sj.startswith(t) or (sj.startswith("#") and sj.lstrip("#").strip().startswith(t))
            for t in targets
        ):
            end_idx = j
            break
    return lines[start_idx:end_idx]


def extract_bullet_texts(section_lines: List[str]) -> List[str]:
    bullets: List[str] = []
    for l in section_lines:
        ls = l.strip()
        if ls.startswith("- "):
            bullets.append(ls[2:].strip())
    return bullets


def get_last_nonempty_lines(lines: List[str], count: int) -> List[str]:
    nonempty = [l.rstrip("\r\n") for l in lines if l.strip() != ""]
    return nonempty[-count:] if len(nonempty) >= count else nonempty


def tokenize_numbers(text: str) -> List[str]:
    return re.findall(r'\b\d+\b', text)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "summary_overall_columns": 0.0,
        "summary_overall_metric_values": 0.0,
        "yes_by_role_columns": 0.0,
        "yes_by_role_counts": 0.0,
        "meeting_minutes_title": 0.0,
        "meeting_minutes_decisions": 0.0,
        "meeting_minutes_action_items": 0.0,
        "meeting_minutes_next_meeting": 0.0,
        "followup_email_subject": 0.0,
        "followup_email_mentions_park": 0.0,
        "followup_email_attendee_and_volunteer_counts": 0.0,
        "followup_email_first_walk_date": 0.0,
        "followup_email_next_meeting_details": 0.0,
        "followup_email_signoff_and_footer": 0.0,
    }

    # Load input data
    attendees_path = workspace / "input" / "attendees.csv"
    meeting_notes_path = workspace / "input" / "meeting_notes.txt"
    mailer_config_path = workspace / "input" / "mailer_config.yaml"

    attendees_data = load_csv_dicts(attendees_path)
    meeting_notes_text = read_text_file(meeting_notes_path)
    mailer_cfg = parse_simple_yaml_map(mailer_config_path) if mailer_config_path.exists() else None

    overall_counts = None
    yes_by_role_expected: Dict[str, int] = {}
    if attendees_data is not None:
        rows, _headers = attendees_data
        try:
            overall_counts, yes_by_role_expected = compute_attendance_stats(rows)
        except Exception:
            overall_counts = None

    meeting_info = None
    if meeting_notes_text is not None:
        meeting_info = parse_meeting_notes(meeting_notes_text)

    # Check summary_overall.csv
    summary_path = workspace / "output" / "summary_overall.csv"
    summary_data = load_csv_dicts(summary_path)
    if summary_data is not None:
        summary_rows, summary_headers = summary_data
        # Columns check
        if summary_headers == ["metric", "value"]:
            scores["summary_overall_columns"] = 1.0
        # Values check
        if overall_counts is not None:
            # Build dict metric -> value (parsed as int)
            ok = True
            metrics_found: Dict[str, int] = {}
            try:
                for row in summary_rows:
                    metric = (row.get("metric") or "").strip()
                    value_str = (row.get("value") or "").strip()
                    if metric:
                        # attempt to parse int
                        value_int = int(value_str)
                        metrics_found[metric] = value_int
                required = ["total_attendees", "yes", "maybe", "no"]
                for k in required:
                    if k not in metrics_found:
                        ok = False
                        break
                    if metrics_found[k] != overall_counts[k]:
                        ok = False
                        break
            except Exception:
                ok = False
            if ok:
                scores["summary_overall_metric_values"] = 1.0

    # Check yes_by_role.csv
    ybr_path = workspace / "output" / "yes_by_role.csv"
    ybr_data = load_csv_dicts(ybr_path)
    if ybr_data is not None:
        ybr_rows, ybr_headers = ybr_data
        # Columns check
        if ybr_headers == ["role", "yes_count"]:
            scores["yes_by_role_columns"] = 1.0
        # Counts check
        if overall_counts is not None and yes_by_role_expected is not None:
            ok = True
            seen_roles: Dict[str, int] = {}
            try:
                for row in ybr_rows:
                    role = (row.get("role") or "").strip()
                    val_str = (row.get("yes_count") or "").strip()
                    val_int = int(val_str)
                    # role must exist in input roles
                    if role not in yes_by_role_expected:
                        ok = False
                        break
                    # count must match expected for that role
                    if yes_by_role_expected.get(role, 0) != val_int:
                        ok = False
                        break
                    if role in seen_roles:
                        ok = False  # duplicate role rows not allowed
                        break
                    seen_roles[role] = val_int
                # Ensure all roles with expected >0 are present
                for role, cnt in yes_by_role_expected.items():
                    if cnt > 0 and role not in seen_roles:
                        ok = False
                        break
            except Exception:
                ok = False
            if ok:
                scores["yes_by_role_counts"] = 1.0

    # Check meeting_minutes.md
    minutes_path = workspace / "output" / "meeting_minutes.md"
    minutes_text = read_text_file(minutes_path)
    if minutes_text is not None:
        minutes_lines = minutes_text.splitlines()
        # Title check
        # First non-empty line must equal title with em dash
        expected_title = "Friends of QE Park Art Walks — Planning Meeting Minutes"
        first_nonempty = None
        for l in minutes_lines:
            if l.strip() != "":
                first_nonempty = l.strip()
                break
        if first_nonempty == expected_title:
            scores["meeting_minutes_title"] = 1.0

        # Decisions check
        if meeting_info is not None:
            decisions_expected: List[str] = meeting_info.get("decisions", [])  # type: ignore
            decisions_section_lines = find_section_lines(minutes_lines, "Decisions")
            decision_bullets = extract_bullet_texts(decisions_section_lines)
            if decisions_expected:
                all_present = True
                for dec in decisions_expected:
                    if not any(dec in b for b in decision_bullets):
                        all_present = False
                        break
                if all_present and len(decision_bullets) >= len(decisions_expected):
                    scores["meeting_minutes_decisions"] = 1.0

        # Action Items check
        if meeting_info is not None:
            actions_expected: List[Tuple[str, str, str]] = meeting_info.get("actions", [])  # type: ignore
            action_section_lines = find_section_lines(minutes_lines, "Action Items")
            action_bullets = [l.strip() for l in action_section_lines if l.strip().startswith("- ")]
            # Build expected bullet strings
            expected_bullets = [f"- {assignee} — {task} (due {due})" for assignee, task, due in actions_expected]
            if actions_expected:
                all_actions_present = True
                for exp in expected_bullets:
                    if exp not in action_bullets:
                        all_actions_present = False
                        break
                if all_actions_present:
                    scores["meeting_minutes_action_items"] = 1.0

        # Next Meeting check
        if meeting_info is not None:
            nm = meeting_info.get("next_meeting", {})  # type: ignore
            nm_section_lines = find_section_lines(minutes_lines, "Next Meeting")
            nm_text_block = "\n".join(nm_section_lines)
            dt = nm.get("date_time")
            loc = nm.get("location")
            purp = nm.get("purpose")
            if dt and loc and purp:
                if (dt in nm_text_block) and (loc in nm_text_block) and (purp in nm_text_block):
                    scores["meeting_minutes_next_meeting"] = 1.0

    # Check followup_email.txt
    email_path = workspace / "output" / "followup_email.txt"
    email_text = read_text_file(email_path)
    if email_text is not None:
        email_lines = email_text.splitlines()
        # Subject check
        if mailer_cfg is not None:
            subject_prefix = mailer_cfg.get("subject_prefix")
            if subject_prefix is not None:
                expected_subject = f"Subject: {subject_prefix} Art Walk Follow-Up and Next Steps"
                if email_lines:
                    if email_lines[0].strip() == expected_subject:
                        scores["followup_email_subject"] = 1.0

        # Body text (after first line)
        body_lines = email_lines[1:] if len(email_lines) > 1 else []
        body_text = "\n".join(body_lines)

        # Mentions park exact phrase
        if "Queen Elizabeth Olympic Park" in body_text:
            scores["followup_email_mentions_park"] = 1.0

        # Attendee and volunteer counts present as numeric tokens
        if overall_counts is not None:
            total_yes = overall_counts["yes"]
            # volunteers among yes
            volunteer_yes = 0
            if yes_by_role_expected is not None and "Volunteer" in yes_by_role_expected:
                volunteer_yes = yes_by_role_expected["Volunteer"]
            nums = tokenize_numbers(body_text)
            if str(total_yes) in nums and str(volunteer_yes) in nums:
                scores["followup_email_attendee_and_volunteer_counts"] = 1.0

        # First walk date referenced
        if meeting_info is not None:
            first_walk_date = meeting_info.get("first_walk_date")
            if first_walk_date and first_walk_date in body_text:
                scores["followup_email_first_walk_date"] = 1.0

        # Next meeting details included
        if meeting_info is not None:
            nm = meeting_info.get("next_meeting", {})  # type: ignore
            dt = nm.get("date_time")
            loc = nm.get("location")
            purp = nm.get("purpose")
            if dt and loc and purp:
                if (dt in body_text) and (loc in body_text) and (purp in body_text):
                    scores["followup_email_next_meeting_details"] = 1.0

        # Signoff and footer checks
        if mailer_cfg is not None:
            signoff = mailer_cfg.get("signoff")
            from_name = mailer_cfg.get("from_name")
            from_title = mailer_cfg.get("from_title")
            from_affiliation = mailer_cfg.get("from_affiliation")
            footer_note = mailer_cfg.get("footer_note")
            if all(x is not None for x in [signoff, from_name, from_title, from_affiliation, footer_note]):
                # Last non-empty lines should end with [signoff, from_name, from_title, from_affiliation, footer_note] in that order
                tail = get_last_nonempty_lines(email_lines, 5)
                if len(tail) >= 5:
                    if (
                        tail[-5].strip() == signoff
                        and tail[-4].strip() == from_name
                        and tail[-3].strip() == from_title
                        and tail[-2].strip() == from_affiliation
                        and tail[-1].strip() == footer_note
                    ):
                        scores["followup_email_signoff_and_footer"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()