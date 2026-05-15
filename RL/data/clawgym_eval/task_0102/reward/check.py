import json
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_simple_yaml(path: Path):
    """
    Minimal YAML loader for a flat mapping of scalars: key: value
    Handles inline comments and simple quoting.
    """
    text = read_text_file(path)
    if text is None:
        return None
    data = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # remove comments not inside quotes (heuristic: split at first #)
        if "#" in line:
            hash_index = line.find("#")
            if hash_index != -1:
                line = line[:hash_index].rstrip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        # Try to coerce numbers
        coerced = val
        if val != "":
            low = val.lower()
            if low in ("null", "none"):
                coerced = None
            elif low in ("true", "false"):
                coerced = True if low == "true" else False
            else:
                try:
                    if re.fullmatch(r"[+-]?\d+", val):
                        coerced = int(val)
                    elif re.fullmatch(r"[+-]?\d+\.\d+", val):
                        coerced = float(val)
                except Exception:
                    coerced = val
        data[key] = coerced
    return data


def to_int(value):
    try:
        return int(value)
    except Exception:
        try:
            f = float(value)
            if f.is_integer():
                return int(f)
        except Exception:
            return None
    return None


def fmt_two_dec(value) -> str:
    try:
        return f"{float(value):.2f}"
    except Exception:
        return None


def compute_active_players_info(roster):
    if not isinstance(roster, list):
        return None
    active = [p for p in roster if isinstance(p, dict) and p.get("status") == "active"]
    attendee_count = len(active)
    # roles mapping
    role_to_name = {}
    for p in active:
        roles = p.get("roles") or []
        name = p.get("name")
        for r in roles:
            if r not in role_to_name:
                role_to_name[r] = name
    # allergies
    allergies = []
    for p in active:
        for a in (p.get("allergies") or []):
            if isinstance(a, str):
                allergies.append(a.strip().lower())
    unique_allergies = sorted(set([a for a in allergies if a]))
    return {
        "active": active,
        "attendee_count": attendee_count,
        "role_to_name": role_to_name,
        "unique_allergies": unique_allergies,
        "allergies_str": ", ".join(unique_allergies) if unique_allergies else "none",
    }


def find_title_with_minutes_index(text: str, title: str, minutes: int) -> int:
    """
    Find index of title in text and verify that within a small window (100 chars) around it,
    the minutes number appears as a standalone number.
    """
    if text is None:
        return -1
    idx = text.find(title)
    if idx == -1:
        return -1
    window_start = max(0, idx - 50)
    window_end = min(len(text), idx + len(title) + 100)
    window = text[window_start:window_end]
    minutes_pattern = re.compile(rf"\b{minutes}\b")
    if minutes_pattern.search(window):
        return idx
    # broader search
    broader_start = max(0, idx - 200)
    broader_end = min(len(text), idx + len(title) + 200)
    broader = text[broader_start:broader_end]
    if minutes_pattern.search(broader):
        return idx
    return -1


def line_matches_item(line: str, assignee: str, due_date: str, keywords: list, require_pending: bool = True) -> bool:
    low = line.lower()
    if "assignee" not in low or "task" not in low or "due" not in low or "status" not in low:
        return False
    if assignee.lower() not in low:
        return False
    if due_date not in line:
        return False
    if require_pending and "pending" not in low:
        return False
    for kw in keywords:
        if kw.lower() not in low:
            return False
    return True


def compute_due_date(base_date_str: str, offset_days: int) -> str:
    try:
        base_date = datetime.strptime(base_date_str, "%Y-%m-%d").date()
        due = base_date + timedelta(days=offset_days)
        return due.isoformat()
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_values_set_correctly": 0.0,
        "curriculum_header_info": 0.0,
        "curriculum_attendee_and_budget": 0.0,
        "curriculum_allergy_constraints": 0.0,
        "curriculum_agenda_correct": 0.0,
        "meeting_notes_items_book_location": 0.0,
        "meeting_notes_items_confirm_attendance": 0.0,
        "meeting_notes_items_snack_list": 0.0,
        "meeting_notes_items_water_coolers": 0.0,
        "coach_email_required_content": 0.0,
        "team_message_required_content": 0.0,
    }

    # Expected config values to verify edits
    expected_date = "2026-05-20"
    expected_start_time = "16:00"
    expected_location = "Team Film Room"
    expected_budget = 120
    expected_minutes = 90

    # Load config
    config_path = workspace / "config" / "workshop.yaml"
    config = load_simple_yaml(config_path) if config_path.exists() else None

    if isinstance(config, dict):
        date_ok = str(config.get("workshop_date", "")).strip() == expected_date
        time_ok = str(config.get("start_time", "")).strip() == expected_start_time
        loc_ok = str(config.get("location", "")).strip() == expected_location
        budget_val = config.get("total_food_budget")
        minutes_val = config.get("target_total_minutes")
        budget_ok = (to_int(budget_val) == expected_budget)
        minutes_ok = (to_int(minutes_val) == expected_minutes)
        if date_ok and time_ok and loc_ok and budget_ok and minutes_ok:
            scores["config_values_set_correctly"] = 1.0

    # Load inputs
    roster = load_json_file(workspace / "input" / "roster.json")
    guidelines = load_json_file(workspace / "input" / "guidelines.json")
    info = compute_active_players_info(roster) if roster is not None else None

    # Compute derived expected values
    attendee_count = None
    allergies_str = None
    per_person_budget_str = None
    modules = []
    sum_default_minutes = None
    qna_minutes = None

    if info and config:
        attendee_count = info["attendee_count"]
        allergies_str = info["allergies_str"]
        budget_int = to_int(config.get("total_food_budget"))
        if budget_int is not None and attendee_count and attendee_count > 0:
            per_person_budget_str = fmt_two_dec(budget_int / attendee_count)
        if isinstance(guidelines, dict) and isinstance(guidelines.get("modules"), list):
            modules = [(m.get("title"), to_int(m.get("minutes"))) for m in guidelines["modules"]]
            if all(isinstance(t, str) and isinstance(mn, int) for t, mn in modules):
                sum_default_minutes = sum(mn for _, mn in modules)
                if to_int(config.get("target_total_minutes")) is not None:
                    qna_minutes = to_int(config.get("target_total_minutes")) - sum_default_minutes

    # Read output files
    curriculum_path = workspace / "output" / "curriculum.md"
    notes_path = workspace / "output" / "meeting_notes.md"
    coach_email_path = workspace / "output" / "emails" / "coach_email.txt"
    team_msg_path = workspace / "output" / "emails" / "team_message.txt"

    curriculum_text = read_text_file(curriculum_path)
    notes_text = read_text_file(notes_path)
    coach_email_text = read_text_file(coach_email_path)
    team_msg_text = read_text_file(team_msg_path)

    # curriculum_header_info: includes date, start time, location from config
    if curriculum_text is not None and isinstance(config, dict):
        conf_date = str(config.get("workshop_date", "")).strip()
        conf_time = str(config.get("start_time", "")).strip()
        conf_loc = str(config.get("location", "")).strip()
        has_date = conf_date != "" and conf_date in curriculum_text
        has_time = conf_time != "" and conf_time in curriculum_text
        has_loc = conf_loc != "" and conf_loc in curriculum_text
        if has_date and has_time and has_loc:
            scores["curriculum_header_info"] = 1.0

    # curriculum_attendee_and_budget
    if curriculum_text is not None and attendee_count is not None and per_person_budget_str is not None:
        attendee_ok = bool(re.search(rf"attendee[\s_-]?count[^0-9]*\b{attendee_count}\b", curriculum_text, re.I))
        budget_ok = bool(re.search(rf"per[\s_-]?person[\s_-]?budget[^0-9]*{re.escape(per_person_budget_str)}\b", curriculum_text, re.I))
        if attendee_ok and budget_ok:
            scores["curriculum_attendee_and_budget"] = 1.0

    # curriculum_allergy_constraints: labeled clearly and list shown (case-insensitive)
    if curriculum_text is not None and allergies_str is not None:
        low_text = curriculum_text.lower()
        label_ok = ("allergy" in low_text and "constraint" in low_text and "active" in low_text and "player" in low_text)
        list_ok = allergies_str.lower() in low_text
        if label_ok and list_ok:
            scores["curriculum_allergy_constraints"] = 1.0

    # curriculum_agenda_correct
    if curriculum_text is not None and modules and qna_minutes is not None and qna_minutes >= 0:
        indices = []
        ok = True
        for title, minutes in modules:
            idx = find_title_with_minutes_index(curriculum_text, title, minutes)
            if idx == -1:
                ok = False
                break
            indices.append(idx)
        if ok:
            order_ok = all(indices[i] < indices[i + 1] for i in range(len(indices) - 1))
            qna_idx = find_title_with_minutes_index(curriculum_text, "Q&A", qna_minutes)
            if order_ok and qna_idx != -1 and (not indices or qna_idx > indices[-1]):
                scores["curriculum_agenda_correct"] = 1.0

    # meeting_notes items
    if notes_text is not None and info and config:
        lines = [ln.strip() for ln in notes_text.splitlines() if ln.strip()]
        # Compute due dates from config
        workshop_date = str(config.get("workshop_date", "")).strip()
        due_book = compute_due_date(workshop_date, -7) if workshop_date else None
        due_confirm = compute_due_date(workshop_date, -5) if workshop_date else None
        due_snack = compute_due_date(workshop_date, -3) if workshop_date else None
        due_water = compute_due_date(workshop_date, 0) if workshop_date else None

        captain = info["role_to_name"].get("captain")
        nutrition_rep = info["role_to_name"].get("nutrition_rep")
        equipment_mgr = info["role_to_name"].get("equipment_mgr")

        # Book location (captain)
        book_ok = False
        if captain and due_book:
            for ln in lines:
                if line_matches_item(ln, captain, due_book, ["book", "location"]):
                    book_ok = True
                    break
        if book_ok:
            scores["meeting_notes_items_book_location"] = 1.0

        # Confirm attendance (captain)
        confirm_ok = False
        if captain and due_confirm:
            for ln in lines:
                if line_matches_item(ln, captain, due_confirm, ["confirm", "attendance"]):
                    confirm_ok = True
                    break
        if confirm_ok:
            scores["meeting_notes_items_confirm_attendance"] = 1.0

        # Snack list (nutrition_rep) - based on active players' allergies
        snack_ok = False
        if nutrition_rep and due_snack:
            allergy_keywords = (info["unique_allergies"] if info and "unique_allergies" in info else [])
            # Always require "snack" in task; also encourage "list"
            base_keywords = ["snack"]
            # Include each allergy keyword to ensure it's reflected
            keywords = base_keywords + allergy_keywords
            for ln in lines:
                if line_matches_item(ln, nutrition_rep, due_snack, keywords):
                    snack_ok = True
                    break
        if snack_ok:
            scores["meeting_notes_items_snack_list"] = 1.0

        # Water coolers (equipment_mgr)
        water_ok = False
        if equipment_mgr and due_water:
            for ln in lines:
                if line_matches_item(ln, equipment_mgr, due_water, ["water", "cooler"]):
                    water_ok = True
                    break
        if water_ok:
            scores["meeting_notes_items_water_coolers"] = 1.0

    # coach_email_required_content
    if coach_email_text is not None and attendee_count is not None and per_person_budget_str is not None and modules and qna_minutes is not None and isinstance(config, dict):
        conf_date = str(config.get("workshop_date", "")).strip()
        conf_time = str(config.get("start_time", "")).strip()
        conf_loc = str(config.get("location", "")).strip()
        ctext = coach_email_text
        has_date = conf_date != "" and conf_date in ctext
        has_time = conf_time != "" and conf_time in ctext
        has_loc = conf_loc != "" and conf_loc in ctext
        has_attendee = re.search(rf"\b{attendee_count}\b", ctext) is not None
        has_budget = re.search(rf"\b{re.escape(per_person_budget_str)}\b", ctext) is not None
        agenda_ok = True
        for title, minutes in modules:
            if title not in ctext or re.search(rf"\b{minutes}\b", ctext) is None:
                agenda_ok = False
                break
        qna_ok = ("Q&A" in ctext) and (re.search(rf"\b{qna_minutes}\b", ctext) is not None)
        if has_date and has_time and has_loc and has_attendee and has_budget and agenda_ok and qna_ok:
            scores["coach_email_required_content"] = 1.0

    # team_message_required_content
    if team_msg_text is not None and per_person_budget_str is not None and info and isinstance(config, dict):
        conf_date = str(config.get("workshop_date", "")).strip()
        conf_time = str(config.get("start_time", "")).strip()
        conf_loc = str(config.get("location", "")).strip()
        ttext = team_msg_text
        has_date = conf_date != "" and conf_date in ttext
        has_time = conf_time != "" and conf_time in ttext
        has_loc = conf_loc != "" and conf_loc in ttext
        has_budget = re.search(rf"\b{re.escape(per_person_budget_str)}\b", ttext) is not None
        # allergies constraints (active players)
        allergies_str = info["allergies_str"]
        allergies_ok = allergies_str.lower() in ttext.lower()
        # RSVP "I'm in" and deadline 5 days before
        deadline = compute_due_date(conf_date, -5) if conf_date else None
        low = ttext.lower()
        im_in_ok = ("i'm in" in low) or ("i’m in" in low)
        deadline_ok = (deadline in ttext) if deadline else False
        if has_date and has_time and has_loc and has_budget and allergies_ok and im_in_ok and deadline_ok:
            scores["team_message_required_content"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()