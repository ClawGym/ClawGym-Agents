import json
import sys
import re
import csv
from pathlib import Path
from datetime import datetime, timedelta


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            return list(reader)
    except Exception:
        return None


def _safe_json_load(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_policy_yaml(path: Path):
    """
    Minimal YAML parser for expected simple structure:
    - timezone: Europe/Paris
    - default_reminders_days_before: [2, 0]
    - event_start_time: "09:00"
    """
    txt = _read_text(path)
    if txt is None:
        return None
    timezone = None
    offsets = None
    event_start_time = None
    for raw_line in txt.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if key == "timezone":
            timezone = val.strip().strip('"').strip("'")
        elif key == "event_start_time":
            event_start_time = val.strip().strip('"').strip("'")
        elif key == "default_reminders_days_before":
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                if inner == "":
                    offsets = []
                else:
                    offs = []
                    for p in inner.split(","):
                        p_clean = p.strip().strip('"').strip("'")
                        try:
                            offs.append(int(p_clean))
                        except Exception:
                            return None
                    offsets = offs
            else:
                return None
    if timezone is None or offsets is None or event_start_time is None:
        return None
    if not re.fullmatch(r"\d{2}:\d{2}", event_start_time):
        return None
    return {"timezone": timezone, "default_reminders_days_before": offsets, "event_start_time": event_start_time}


def _iso_date_valid(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _parse_minutes(raw_text: str):
    """
    Parse decisions and action items from the raw minutes markdown text.
    Returns dict with keys:
    - decisions: list of decision strings
    - actions: list of dicts with keys assignees (list), task, tags (list), due_date, priority
    - next_meetup_exact: exact "YYYY-MM-DD at HH:MM (CET)" substring if present, else None
    """
    decisions = []
    actions = []
    next_meetup_exact = None
    lines = raw_text.splitlines()
    dec_re = re.compile(r"^\s*-\s*DECISION:\s*(.+?)\s*$")
    act_re = re.compile(
        r"^\s*-\s*ACTION:\s*(?P<assignees>.+?)\s*-\s*(?P<task>.+?)\s*\(tags:\s*(?P<tags>[^)]*?)\)\s*due\s*(?P<due>\d{4}-\d{2}-\d{2})\s*priority:\s*(?P<priority>\w+)\s*$"
    )
    for line in lines:
        m_dec = dec_re.match(line)
        if m_dec:
            decisions.append(m_dec.group(1).strip())
            continue
        m_act = act_re.match(line)
        if m_act:
            assignees_raw = m_act.group("assignees").strip()
            assignees = [a.strip() for a in assignees_raw.split("&")]
            task = m_act.group("task").strip()
            tags_raw = m_act.group("tags").strip()
            tags = [t.strip() for t in tags_raw.split(",") if t.strip() != ""]
            due = m_act.group("due").strip()
            priority = m_act.group("priority").strip()
            actions.append(
                {
                    "assignees": assignees,
                    "task": task,
                    "tags": tags,
                    "due_date": due,
                    "priority": priority,
                }
            )
    dt_match = re.search(r"\b(\d{4}-\d{2}-\d{2} at \d{2}:\d{2} \(CET\))\b", raw_text)
    if dt_match:
        next_meetup_exact = dt_match.group(1)
    return {
        "decisions": decisions,
        "actions": actions,
        "next_meetup_exact": next_meetup_exact,
    }


def _build_expected_actions(parsed_minutes: dict, participants_map: dict):
    """
    Expand and filter actions by participants.
    """
    expected = []
    for act in parsed_minutes.get("actions", []):
        for name in act["assignees"]:
            if name in participants_map:
                expected.append(
                    {
                        "assignee_name": name,
                        "assignee_email": participants_map[name],
                        "task": act["task"],
                        "due_date": act["due_date"],
                        "priority": act["priority"],
                        "tags": list(act["tags"]),
                    }
                )
    return expected


def _find_section_lines(md_text: str, title: str):
    """
    Find lines belonging to a section with a given title ('Decisions' or 'Action Items').
    Header can be plain 'Decisions' or markdown '# Decisions'.
    Returns list of lines in the section (excluding the header) or None.
    """
    lines = md_text.splitlines()

    def is_header(line: str, t: str) -> bool:
        stripped = line.strip()
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        return stripped == t

    header_indices = [i for i, ln in enumerate(lines) if is_header(ln, title)]
    if not header_indices:
        return None
    start_idx = header_indices[0] + 1
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        s_nohash = lines[j].strip().lstrip("#").strip()
        if s_nohash in ("Decisions", "Action Items"):
            end_idx = j
            break
    return lines[start_idx:end_idx]


def _extract_bullet_lines(lines):
    return [ln.strip() for ln in lines if ln.strip().startswith(("-", "*"))]


def _expected_reminders(expected_actions, policy):
    """
    Build expected reminders entries as list of dicts with keys:
    action_id, assignee_email, task, remind_on, reminder_type
    """
    offsets = policy["default_reminders_days_before"]
    result = []
    for idx, act in enumerate(expected_actions, start=1):
        due_dt = datetime.strptime(act["due_date"], "%Y-%m-%d")
        for off in offsets:
            remind_on_dt = due_dt - timedelta(days=off)
            remind_on = remind_on_dt.strftime("%Y-%m-%d")
            reminder_type = "due_day" if off == 0 else "before_due"
            result.append(
                {
                    "action_id": str(idx),
                    "assignee_email": act["assignee_email"],
                    "task": act["task"],
                    "remind_on": remind_on,
                    "reminder_type": reminder_type,
                }
            )
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "action_items_json_exists_and_valid": 0.0,
        "action_items_json_correct_content": 0.0,
        "clean_minutes_sections": 0.0,
        "clean_minutes_decisions_correct": 0.0,
        "clean_minutes_action_items_correct": 0.0,
        "follow_up_subject_and_signoff": 0.0,
        "follow_up_placeholders_filled": 0.0,
        "follow_up_action_items_list_complete": 0.0,
        "follow_up_next_meetup_exact": 0.0,
        "reminders_csv_valid": 0.0,
        "reminders_csv_correct_content": 0.0,
        "reminders_ics_event_count": 0.0,
        "reminders_ics_dtstart_correct": 0.0,
    }

    # Input paths
    participants_path = workspace / "input" / "participants.csv"
    raw_minutes_path = workspace / "input" / "raw_minutes.md"
    email_draft_path = workspace / "input" / "follow_up_email_draft.md"
    policy_path = workspace / "input" / "reminder_policy.yaml"

    # Load inputs
    participants_rows = _load_csv_rows(participants_path)
    participants_map = {}
    if participants_rows:
        if {"name", "email"}.issubset(set(participants_rows[0].keys())):
            for r in participants_rows:
                n = (r.get("name") or "").strip()
                e = (r.get("email") or "").strip()
                if n and e:
                    participants_map[n] = e

    raw_minutes_text = _read_text(raw_minutes_path)
    parsed_minutes = _parse_minutes(raw_minutes_text) if raw_minutes_text is not None else None

    # Build expected actions and reminders
    expected_actions = []
    if parsed_minutes and participants_map:
        expected_actions = _build_expected_actions(parsed_minutes, participants_map)

    expected_json_array = []
    for i, act in enumerate(expected_actions, start=1):
        expected_json_array.append(
            {
                "id": i,
                "assignee_name": act["assignee_name"],
                "assignee_email": act["assignee_email"],
                "task": act["task"],
                "due_date": act["due_date"],
                "priority": act["priority"],
                "tags": list(act["tags"]),
            }
        )

    # Validate output/action_items.json
    ai_json_path = workspace / "output" / "action_items.json"
    ai_json = _safe_json_load(ai_json_path)
    valid_struct = False
    if isinstance(ai_json, list):
        ids = []
        valid_struct = True
        for item in ai_json:
            if not isinstance(item, dict):
                valid_struct = False
                break
            required_fields = {"id", "assignee_name", "assignee_email", "task", "due_date", "priority", "tags"}
            if not required_fields.issubset(set(item.keys())):
                valid_struct = False
                break
            if not isinstance(item.get("id"), int):
                valid_struct = False
                break
            if not isinstance(item.get("assignee_name"), str):
                valid_struct = False
                break
            if not isinstance(item.get("assignee_email"), str) or "@" not in item.get("assignee_email"):
                valid_struct = False
                break
            if not isinstance(item.get("task"), str):
                valid_struct = False
                break
            if not isinstance(item.get("due_date"), str) or not _iso_date_valid(item.get("due_date")):
                valid_struct = False
                break
            if not isinstance(item.get("priority"), str):
                valid_struct = False
                break
            if not isinstance(item.get("tags"), list) or not all(isinstance(t, str) for t in item.get("tags")):
                valid_struct = False
                break
            ids.append(item["id"])
        if valid_struct and ids == list(range(1, len(ai_json) + 1)):
            scores["action_items_json_exists_and_valid"] = 1.0

        # Content validation against expected (ignore tag order, allow extra keys)
        if valid_struct and expected_json_array:
            def _normalize(items):
                res = []
                for it in items:
                    res.append({
                        "id": int(it["id"]),
                        "assignee_name": it["assignee_name"],
                        "assignee_email": it["assignee_email"],
                        "task": it["task"],
                        "due_date": it["due_date"],
                        "priority": it["priority"],
                        "tags": sorted(list(it["tags"])),
                    })
                return res

            if _normalize(ai_json) == _normalize(expected_json_array):
                scores["action_items_json_correct_content"] = 1.0

    # Validate output/clean_minutes.md
    clean_md_path = workspace / "output" / "clean_minutes.md"
    clean_md_text = _read_text(clean_md_path)
    if clean_md_text is not None:
        decisions_lines = _find_section_lines(clean_md_text, "Decisions")
        action_items_lines = _find_section_lines(clean_md_text, "Action Items")
        if decisions_lines is not None and action_items_lines is not None:
            scores["clean_minutes_sections"] = 1.0

        if decisions_lines is not None and parsed_minutes and parsed_minutes.get("decisions"):
            decisions_content = "\n".join(decisions_lines)
            ok = True
            for dec in parsed_minutes["decisions"]:
                if dec not in decisions_content:
                    ok = False
                    break
            if ok:
                scores["clean_minutes_decisions_correct"] = 1.0

        if action_items_lines is not None and expected_actions:
            bullets = _extract_bullet_lines(action_items_lines)
            matched = [False] * len(expected_actions)
            for idx, act in enumerate(expected_actions):
                expected_tokens = [
                    act["assignee_name"],
                    f"({act['assignee_email']})",
                    act["task"],
                    act["due_date"],
                    act["priority"],
                ] + act["tags"]
                for b in bullets:
                    if all(tok in b for tok in expected_tokens):
                        matched[idx] = True
                        break
            if all(matched) and len(bullets) == len(expected_actions):
                scores["clean_minutes_action_items_correct"] = 1.0

    # Validate output/follow_up_email.md
    email_out_path = workspace / "output" / "follow_up_email.md"
    email_out_text = _read_text(email_out_path)
    expected_subject = None
    expected_signoff = None
    draft_text = _read_text(email_draft_path)
    if draft_text is not None:
        draft_lines = draft_text.splitlines()
        if draft_lines:
            expected_subject = draft_lines[0].strip()
        non_empty = [ln.strip() for ln in draft_lines if ln.strip() != ""]
        if len(non_empty) >= 2:
            expected_signoff = (non_empty[-2], non_empty[-1])

    if email_out_text is not None:
        lines = email_out_text.splitlines()
        ok_sub = False
        ok_sign = False
        if expected_subject and lines:
            if lines[0].strip() == expected_subject:
                ok_sub = True
        if expected_signoff:
            out_non_empty = [ln.strip() for ln in lines if ln.strip() != ""]
            if len(out_non_empty) >= 2 and (out_non_empty[-2], out_non_empty[-1]) == expected_signoff:
                ok_sign = True
        if ok_sub and ok_sign:
            scores["follow_up_subject_and_signoff"] = 1.0

        # Placeholders removed and count line near top
        placeholders_absent = ("[DECISIONS_SUMMARY]" not in email_out_text
                               and "[ACTION_ITEMS]" not in email_out_text
                               and "[NEXT_MEETUP]" not in email_out_text)
        n_expected = len(expected_actions)
        count_line_present = False
        top_n = lines[:15] if len(lines) >= 15 else lines
        for ln in top_n:
            if f"Number of action items: {n_expected}" in ln:
                count_line_present = True
                break
        if placeholders_absent and n_expected > 0 and count_line_present:
            scores["follow_up_placeholders_filled"] = 1.0

        # Action items bullets complete
        if expected_actions:
            matched = [False] * len(expected_actions)
            bullet_lines = [ln.strip() for ln in lines if ln.strip().startswith(("-", "*"))]
            email_bullets = [ln for ln in bullet_lines if "@" in ln]
            for idx, act in enumerate(expected_actions):
                tokens = [act["assignee_name"], act["assignee_email"], act["task"], act["due_date"]]
                for bl in email_bullets:
                    if all(tok in bl for tok in tokens):
                        matched[idx] = True
                        break
            if all(matched) and len(email_bullets) >= len(expected_actions):
                scores["follow_up_action_items_list_complete"] = 1.0

        # Next meetup exact text
        if parsed_minutes and parsed_minutes.get("next_meetup_exact"):
            if parsed_minutes["next_meetup_exact"] in email_out_text:
                scores["follow_up_next_meetup_exact"] = 1.0

    # Reminders validation
    policy = _parse_policy_yaml(policy_path) if policy_path.exists() else None
    reminders_csv_path = workspace / "output" / "reminders.csv"
    reminders_ics_path = workspace / "output" / "reminders.ics"

    expected_reminders = []
    if expected_actions and policy:
        expected_reminders = _expected_reminders(expected_actions, policy)

    # reminders.csv validation
    csv_rows = None
    if reminders_csv_path.exists():
        try:
            with reminders_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames
                rows = list(reader)
                csv_rows = rows
                if header == ["action_id", "assignee_email", "task", "remind_on", "reminder_type"]:
                    valid = True
                    for r in rows:
                        if not r.get("action_id") or not r.get("assignee_email") or not r.get("task") or not r.get("remind_on") or not r.get("reminder_type"):
                            valid = False
                            break
                        if not _iso_date_valid(r.get("remind_on")):
                            valid = False
                            break
                        if r.get("reminder_type") not in ("before_due", "due_day"):
                            valid = False
                            break
                    if valid:
                        scores["reminders_csv_valid"] = 1.0
        except Exception:
            csv_rows = None

    if expected_reminders and csv_rows is not None:
        exp_set = set((e["action_id"], e["assignee_email"], e["task"], e["remind_on"], e["reminder_type"]) for e in expected_reminders)
        act_set = set((r.get("action_id"), r.get("assignee_email"), r.get("task"), r.get("remind_on"), r.get("reminder_type")) for r in csv_rows)
        if exp_set == act_set and len(csv_rows) == len(expected_reminders):
            scores["reminders_csv_correct_content"] = 1.0

    # reminders.ics validation against CSV (must equal rows count) and policy time
    ics_text = _read_text(reminders_ics_path)
    if ics_text is not None:
        vevent_count = len(re.findall(r"BEGIN:VEVENT", ics_text))
        end_count = len(re.findall(r"END:VEVENT", ics_text))
        if csv_rows is not None:
            if vevent_count == len(csv_rows) and end_count == vevent_count:
                scores["reminders_ics_event_count"] = 1.0
        else:
            # Fallback: ensure balanced VEVENTs if CSV unavailable
            if vevent_count > 0 and vevent_count == end_count:
                scores["reminders_ics_event_count"] = 1.0

        if csv_rows is not None and policy:
            tz = policy["timezone"]
            time_str = policy["event_start_time"]  # "HH:MM"
            hhmm = time_str.replace(":", "")
            dt_ok = True
            for r in csv_rows:
                ymd = (r.get("remind_on") or "").replace("-", "")
                if not re.fullmatch(r"\d{8}", ymd):
                    dt_ok = False
                    break
                dtstamp = f"DTSTART;TZID={tz}:{ymd}T{hhmm}00"
                if dtstamp not in ics_text:
                    dt_ok = False
                    break
            if dt_ok and f"TZID={tz}" in ics_text:
                scores["reminders_ics_dtstart_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()