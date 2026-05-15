import json
import os
import re
import sys
from datetime import datetime

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_valid_date(date_str):
    # Format YYYY-MM-DD
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return True, dt
    except Exception:
        return False, None

def is_valid_time_hhmm(time_str):
    # Format HH:MM, 24-hour clock
    if not isinstance(time_str, str):
        return False
    if not re.fullmatch(r"^[0-2][0-9]:[0-5][0-9]$", time_str):
        return False
    try:
        hh = int(time_str[:2])
        mm = int(time_str[3:])
        return 0 <= hh <= 23 and 0 <= mm <= 59
    except Exception:
        return False

def compute_reward(checks_dict):
    total = len(checks_dict)
    passed = sum(1 for v in checks_dict.values() if v is True)
    if total == 0:
        return 0.0
    return passed / total

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    study_plan_path = os.path.join(output_dir, "study_plan.md")
    progress_path = os.path.join(output_dir, "progress.json")
    tasks_path = os.path.join(output_dir, "tasks.json")
    reminders_path = os.path.join(output_dir, "reminders.json")
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")

    checks = {
        # study_plan.md
        "study_plan_exists": False,
        "study_plan_has_week_markers": False,
        "study_plan_mentions_timed": False,
        "study_plan_mentions_superscore": False,
        "study_plan_mentions_digital_or_module": False,
        "study_plan_has_top_weak_domains_section": False,
        # progress.json
        "progress_exists": False,
        "progress_valid_json": False,
        "progress_has_required_keys": False,
        "progress_section_accuracy_keys": False,
        "progress_prediction_fields": False,
        # tasks.json
        "tasks_exists": False,
        "tasks_valid_json_array": False,
        "tasks_minimum_items": False,
        "tasks_items_fields_valid": False,
        "tasks_due_dates_not_sunday": False,
        # reminders.json
        "reminders_exists": False,
        "reminders_valid_json_array": False,
        "reminders_minimum_items": False,
        "reminders_items_fields_valid": False,
        "reminders_dates_not_sunday": False,
        # learnings
        "learnings_exists": False,
        "learnings_header_format_valid": False,
        "learnings_has_labels": False,
        "learnings_mentions_constraints": False,
    }

    # Check study_plan.md
    if os.path.isfile(study_plan_path):
        content = load_text(study_plan_path)
        if content and content.strip():
            checks["study_plan_exists"] = True
            lc = content.lower()

            # Week markers
            if ("week 1" in lc) and ("week 8" in lc):
                checks["study_plan_has_week_markers"] = True

            # mentions "timed"
            if "timed" in lc:
                checks["study_plan_mentions_timed"] = True

            # superscore or superscoring
            if "superscore" in lc:
                checks["study_plan_mentions_superscore"] = True

            # "Digital SAT" or "module"
            if ("digital sat" in lc) or ("module" in lc):
                checks["study_plan_mentions_digital_or_module"] = True

            # Line or section beginning with "Top weak domains"
            for line in content.splitlines():
                if line.lstrip().lower().startswith("top weak domains"):
                    checks["study_plan_has_top_weak_domains_section"] = True
                    break

    # Check progress.json
    progress_data = None
    if os.path.isfile(progress_path):
        checks["progress_exists"] = True
        progress_data = load_json(progress_path)
        if isinstance(progress_data, dict):
            checks["progress_valid_json"] = True
            required_keys = ["score_history", "section_accuracy", "mistakes_log", "prediction"]
            if all(k in progress_data for k in required_keys):
                if isinstance(progress_data.get("score_history"), list) and \
                   isinstance(progress_data.get("section_accuracy"), dict) and \
                   isinstance(progress_data.get("mistakes_log"), list) and \
                   isinstance(progress_data.get("prediction"), dict):
                    checks["progress_has_required_keys"] = True

                    # section_accuracy keys present and objects
                    sa = progress_data.get("section_accuracy", {})
                    if isinstance(sa, dict) and \
                       "Reading & Writing" in sa and "Math" in sa and \
                       isinstance(sa.get("Reading & Writing"), dict) and \
                       isinstance(sa.get("Math"), dict):
                        checks["progress_section_accuracy_keys"] = True

                    # prediction fields
                    pred = progress_data.get("prediction", {})
                    if isinstance(pred, dict) and \
                       isinstance(pred.get("range"), str) and \
                       isinstance(pred.get("confidence"), str):
                        checks["progress_prediction_fields"] = True

    # Check tasks.json
    tasks_data = None
    if os.path.isfile(tasks_path):
        checks["tasks_exists"] = True
        tasks_data = load_json(tasks_path)
        if isinstance(tasks_data, list):
            checks["tasks_valid_json_array"] = True
            if len(tasks_data) >= 8:
                checks["tasks_minimum_items"] = True

            # Validate items fields and due dates
            items_valid = True
            due_dates_not_sunday = True
            allowed_priorities = {"high", "medium", "low"}

            for item in tasks_data if isinstance(tasks_data, list) else []:
                # Field checks
                if not isinstance(item, dict):
                    items_valid = False
                    break
                # id int
                if "id" not in item or not isinstance(item["id"], int):
                    items_valid = False
                    break
                # text str
                if "text" not in item or not isinstance(item["text"], str):
                    items_valid = False
                    break
                # priority
                if "priority" not in item or item["priority"] not in allowed_priorities:
                    items_valid = False
                    break
                # status pending
                if "status" not in item or item["status"] != "pending":
                    items_valid = False
                    break
                # due format and date not Sunday
                due = item.get("due")
                if not isinstance(due, str) or not re.fullmatch(r"^\d{4}-\d{2}-\d{2}$", due):
                    items_valid = False
                    break
                valid_date, dt = is_valid_date(due)
                if not valid_date:
                    items_valid = False
                    break
                # Sunday check
                if dt.weekday() == 6:  # Sunday
                    due_dates_not_sunday = False

            if checks["tasks_valid_json_array"]:
                if items_valid:
                    checks["tasks_items_fields_valid"] = True
                if items_valid and due_dates_not_sunday:
                    checks["tasks_due_dates_not_sunday"] = True

    # Check reminders.json
    reminders_data = None
    if os.path.isfile(reminders_path):
        checks["reminders_exists"] = True
        reminders_data = load_json(reminders_path)
        if isinstance(reminders_data, list):
            checks["reminders_valid_json_array"] = True
            if len(reminders_data) >= 3:
                checks["reminders_minimum_items"] = True

            items_valid = True
            dates_not_sunday = True
            for r in reminders_data if isinstance(reminders_data, list) else []:
                if not isinstance(r, dict):
                    items_valid = False
                    break
                # id string
                if "id" not in r or not isinstance(r["id"], str):
                    items_valid = False
                    break
                # task string
                if "task" not in r or not isinstance(r["task"], str):
                    items_valid = False
                    break
                # date
                date_str = r.get("date")
                if not isinstance(date_str, str) or not re.fullmatch(r"^\d{4}-\d{2}-\d{2}$", date_str):
                    items_valid = False
                    break
                valid_date, dt = is_valid_date(date_str)
                if not valid_date:
                    items_valid = False
                    break
                # time
                time_str = r.get("time")
                if not is_valid_time_hhmm(time_str):
                    items_valid = False
                    break
                # status pending
                if r.get("status") != "pending":
                    items_valid = False
                    break
                # Sunday check
                if dt.weekday() == 6:
                    dates_not_sunday = False

            if checks["reminders_valid_json_array"]:
                if items_valid:
                    checks["reminders_items_fields_valid"] = True
                if items_valid and dates_not_sunday:
                    checks["reminders_dates_not_sunday"] = True

    # Check LEARNINGS.md
    if os.path.isfile(learnings_path):
        content = load_text(learnings_path)
        if content and content.strip():
            checks["learnings_exists"] = True
            # Header regex
            header_re = re.compile(r'^## \[LRN-[0-9]{8}-[A-Za-z0-9]{3}\] (correction|insight|knowledge_gap|best_practice)', re.MULTILINE)
            if header_re.search(content):
                checks["learnings_header_format_valid"] = True
            # Labels
            if ("Suggested Action" in content) and ("Metadata" in content):
                checks["learnings_has_labels"] = True
            # Mentions constraints
            if ("No study on Sundays" in content) or ("Max session length: 90 minutes" in content):
                checks["learnings_mentions_constraints"] = True

    reward = compute_reward(checks)

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()