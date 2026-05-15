import csv
import json
import os
import re
import sys
from typing import List, Dict, Any

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def normalize(s: str) -> str:
    return s.lower()

def contains_case_insensitive(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()

def get_word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))

def parse_csv_rows(path: str) -> List[List[str]]:
    rows: List[List[str]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                # Keep raw comma-separated lines, ignore empty/whitespace-only lines
                if line.strip() == "":
                    continue
                # Use csv reader to properly handle commas/quotes
                # But first check for tabs (we'll validate separately)
                pass
        # Re-open with csv module for proper parsing
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                # Skip completely empty rows
                if len([c for c in row if c.strip() != ""]) == 0:
                    continue
                rows.append(row)
    except Exception:
        return []
    return rows

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    preferences_path = os.path.join(input_dir, "preferences.json")
    context_path = os.path.join(input_dir, "context.md")
    plan_path = os.path.join(output_dir, "plan.md")
    checklist_path = os.path.join(output_dir, "checklist.csv")

    # Initialize checks (all False by default)
    checks: Dict[str, bool] = {
        "plan_exists": False,
        "plan_non_empty": False,
        "checklist_exists": False,
        "checklist_non_empty": False,
        "plan_has_team_name": False,
        "plan_has_time_per_day_line": False,
        "plan_has_all_days": False,
        "plan_covers_all_topics": False,
        "plan_omits_excluded_tools": False,
        "plan_has_tooling_reference_strings": False,
        "plan_has_quality_notes_100w": False,
        "csv_header_valid": False,
        "csv_rows_10_days_1_to_10": False,
        "csv_time_minutes_all_match": False,
        "csv_hands_on_values_match": False,
        "csv_topics_cover_all": False,
        "csv_omits_excluded_tools_in_topic_objective": False,
        "csv_well_formed_no_tabs": False,
        "plan_has_tooling_reference_label": False,
    }

    # Load inputs
    prefs = load_json(preferences_path)
    context_text = read_text(context_path)  # not scored directly
    plan_text = read_text(plan_path)
    checklist_text = read_text(checklist_path)

    # Existence checks
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        if plan_text.strip() != "":
            checks["plan_non_empty"] = True

    if os.path.isfile(checklist_path):
        checks["checklist_exists"] = True
        if checklist_text.strip() != "":
            checks["checklist_non_empty"] = True

    # If preferences not available, many checks cannot proceed
    team_name = None
    time_per_day = None
    topics: List[str] = []
    exclude_tools: List[str] = []
    hands_on_pref = None

    if isinstance(prefs, dict):
        team_name = prefs.get("team_name")
        time_per_day = prefs.get("time_per_day")
        topics = prefs.get("topics") or []
        exclude_tools = prefs.get("exclude_tools") or []
        hands_on_pref = prefs.get("hands_on")
        # Normalize types
        try:
            if time_per_day is not None:
                time_per_day = int(time_per_day)
        except Exception:
            time_per_day = None
        if isinstance(topics, list):
            topics = [str(t) for t in topics]
        else:
            topics = []
        if isinstance(exclude_tools, list):
            exclude_tools = [str(t) for t in exclude_tools]
        else:
            exclude_tools = []
        if isinstance(hands_on_pref, str):
            if hands_on_pref.strip().lower() in ("true", "yes", "1"):
                hands_on_pref = True
            elif hands_on_pref.strip().lower() in ("false", "no", "0"):
                hands_on_pref = False

    # Plan content validations
    if checks["plan_non_empty"] and isinstance(prefs, dict):
        # team name present in plan
        if isinstance(team_name, str) and team_name.strip():
            if contains_case_insensitive(plan_text, team_name):
                checks["plan_has_team_name"] = True

        # exact time per day line
        if isinstance(time_per_day, int):
            expected_time_line = f"Time per day: {time_per_day} minutes"
            if expected_time_line in plan_text:
                checks["plan_has_time_per_day_line"] = True

        # day sections Day 1..Day 10
        day_all_present = True
        for n in range(1, 11):
            pattern = re.compile(rf"\bDay\s*{n}\b", re.IGNORECASE)
            if not pattern.search(plan_text):
                day_all_present = False
                break
        checks["plan_has_all_days"] = day_all_present

        # topics appear at least once in plan
        topics_ok = True
        plan_lower = plan_text.lower()
        for t in topics:
            if t.strip() == "":
                continue
            if t.lower() not in plan_lower:
                topics_ok = False
                break
        checks["plan_covers_all_topics"] = topics_ok

        # exclude_tools not present anywhere in plan
        excludes_ok = True
        plan_lower = plan_text.lower()
        for e in exclude_tools:
            if e.strip() == "":
                continue
            if e.lower() in plan_lower:
                excludes_ok = False
                break
        checks["plan_omits_excluded_tools"] = excludes_ok

        # Tooling reference section label
        if re.search(r"\bTooling reference\b", plan_text, re.IGNORECASE):
            checks["plan_has_tooling_reference_label"] = True

        # required CLI output substrings present verbatim
        cli_required_substrings = [
            "90Daysofdevops",
            "Commands:",
            "help",
            "run",
            "info",
            "status",
            "Powered by BytesAgain | bytesagain.com",
            "90Daysofdevops v1.0.0",
            "Based on: https://github.com/MichaelCade/90DaysOfDevOps",
            "Stars: 29,378+",
            "Status: ready",
        ]
        cli_ok = True
        for sub in cli_required_substrings:
            if sub not in plan_text:
                cli_ok = False
                break
        checks["plan_has_tooling_reference_strings"] = cli_ok

        # Quality Notes section with >= 100 words
        qn_match = re.search(r"(quality\s*notes)", plan_text, re.IGNORECASE)
        if qn_match:
            start = qn_match.start()
            qn_text = plan_text[start:]
            if get_word_count(qn_text) >= 100:
                checks["plan_has_quality_notes_100w"] = True

    # CSV validations
    if checks["checklist_non_empty"] and isinstance(prefs, dict):
        # no tabs in CSV
        checks["csv_well_formed_no_tabs"] = ("\t" not in checklist_text)

        rows = parse_csv_rows(checklist_path)
        if rows:
            header = rows[0]
            header_names = [h.strip().lower() for h in header]
            expected_headers = ["day", "topic", "objective", "hands_on", "time_minutes", "evaluation"]
            # Validate header contains exactly expected columns (order-insensitive)
            if set(header_names) == set(expected_headers) and len(header_names) == len(expected_headers):
                checks["csv_header_valid"] = True

                # Map column indices
                idx_map = {name: header_names.index(name) for name in expected_headers}

                data_rows = rows[1:]
                # Filter out empty rows (all columns empty)
                filtered_rows = []
                for r in data_rows:
                    if any((c.strip() != "" for c in r)):
                        filtered_rows.append(r)
                data_rows = filtered_rows

                # exactly 10 data rows, days 1..10 without duplicates
                days: List[int] = []
                all_rows_valid = True
                for r in data_rows:
                    # Ensure row has same number of columns
                    if len(r) != len(header):
                        all_rows_valid = False
                        break
                    day_val = r[idx_map["day"]].strip()
                    try:
                        day_int = int(day_val)
                    except Exception:
                        all_rows_valid = False
                        break
                    days.append(day_int)
                if all_rows_valid and len(data_rows) == 10 and set(days) == set(range(1, 11)):
                    checks["csv_rows_10_days_1_to_10"] = True

                # time_minutes equals preference value
                if isinstance(time_per_day, int) and all_rows_valid:
                    tm_ok = True
                    for r in data_rows:
                        tm_val = r[idx_map["time_minutes"]].strip()
                        try:
                            tm_int = int(tm_val)
                        except Exception:
                            tm_ok = False
                            break
                        if tm_int != time_per_day:
                            tm_ok = False
                            break
                    checks["csv_time_minutes_all_match"] = tm_ok

                # hands_on values match preference
                if isinstance(hands_on_pref, bool) and all_rows_valid:
                    expected_hands = "yes" if hands_on_pref else "no"
                    ho_ok = True
                    for r in data_rows:
                        val = r[idx_map["hands_on"]].strip().lower()
                        if val != expected_hands:
                            ho_ok = False
                            break
                    checks["csv_hands_on_values_match"] = ho_ok

                # topics coverage in topic column
                topics_ok_csv = True
                topic_col_values = [r[idx_map["topic"]].strip().lower() for r in data_rows]
                for t in topics:
                    if t.strip() == "":
                        continue
                    if all(t.lower() not in v for v in topic_col_values):
                        topics_ok_csv = False
                        break
                checks["csv_topics_cover_all"] = topics_ok_csv

                # exclude tools not in topic or objective columns
                excludes_ok_csv = True
                for r in data_rows:
                    topic_cell = r[idx_map["topic"]].lower()
                    obj_cell = r[idx_map["objective"]].lower()
                    for e in exclude_tools:
                        e_low = e.lower()
                        if e_low and (e_low in topic_cell or e_low in obj_cell):
                            excludes_ok_csv = False
                            break
                    if not excludes_ok_csv:
                        break
                checks["csv_omits_excluded_tools_in_topic_objective"] = excludes_ok_csv

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline handling: if outputs missing or empty, reward must be 0.0
    if not checks["plan_non_empty"] or not checks["checklist_non_empty"]:
        reward = 0.0

    # Ensure reward bounds [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    # Print JSON result (reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()