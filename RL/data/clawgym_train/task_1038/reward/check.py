import os
import sys
import json
import csv
import re

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

def load_potential_mentors(csv_path):
    mentors_by_name = {}
    if not os.path.isfile(csv_path):
        return mentors_by_name
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Normalize headers to lower for access
            headers = [h.lower() for h in reader.fieldnames] if reader.fieldnames else []
            for row in reader:
                # Lowercase keys mapping
                normalized = {k.lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                name = normalized.get("name", "")
                if not name:
                    continue
                # Store attributes with normalization
                def norm_str(val):
                    return (val or "").strip().lower()
                # Steps ahead as int if possible
                steps_val = normalized.get("steps_ahead", "")
                try:
                    steps_int = int(str(steps_val).strip())
                except Exception:
                    steps_int = None
                mentors_by_name[name] = {
                    "name": name,
                    "steps_ahead": steps_int,
                    "accessibility": norm_str(normalized.get("accessibility", "")),
                    "celebrity": norm_str(normalized.get("celebrity", "")),
                    "met_at_event": norm_str(normalized.get("met_at_event", "")),
                    "creates_content": norm_str(normalized.get("creates_content", "")),
                    "works_at_same_company": norm_str(normalized.get("works_at_same_company", "")),
                }
    except Exception:
        # Return what we could parse; empty if failure
        return mentors_by_name
    return mentors_by_name

def scan_banned_phrase(output_dir, required_files_exist):
    # Only evaluate if at least one required artifact exists, otherwise do not pass (avoid vacuous pass)
    if not required_files_exist:
        return False
    banned = "will you be my mentor?"
    # Scan all text-like files under output/
    for root, dirs, files in os.walk(output_dir):
        for fn in files:
            # Only inspect allowed text/document extensions
            if os.path.splitext(fn)[1].lower() in (".txt", ".csv", ".json", ".jsonl", ".md", ".tsv", ".yaml", ".xml", ".html", ".py"):
                p = os.path.join(root, fn)
                content = read_text(p)
                if content and banned in content.lower():
                    return False
    return True

def split_blocks(text):
    # Split messages by blank lines
    blocks = re.split(r"\n\s*\n+", text.strip()) if text else []
    return [b for b in blocks if b.strip()]

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    plan_path = os.path.join(output_dir, "mentor_outreach_plan.json")
    outreach_path = os.path.join(output_dir, "outreach_messages.md")
    agenda_path = os.path.join(output_dir, "coffee_meeting_agenda.txt")
    tracker_path = os.path.join(output_dir, "follow_up_tracker.csv")

    # Input references
    candidates_csv = os.path.join(input_dir, "potential_mentors.csv")
    # user_profile.json and context_notes.md exist but not strictly needed for deterministic checks

    # Load inputs
    mentors_by_name = load_potential_mentors(candidates_csv)

    # Initialize checks
    checks = {
        "plan_exists": False,
        "plan_valid_json": False,
        "plan_has_required_keys": False,
        "phases_exact_keys": False,
        "cadence_mentions_month": False,
        "selected_mentors_count_ok": False,
        "per_mentor_fields_present": False,
        "selected_mentors_meet_filters": False,
        "engagement_strategy_valid_values": False,
        "engagement_strategy_matches_attributes": False,
        "outreach_exists": False,
        "outreach_per_mentor_constraints": False,
        "agenda_exists": False,
        "agenda_header_and_bullets": False,
        "tracker_exists": False,
        "tracker_header_exact": False,
        "tracker_rows_count_ok": False,
        "no_banned_phrase": False,
    }

    # Derived data
    selected_mentors = []
    plan = None

    # 1) Plan checks
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan, ok = load_json(plan_path)
        if ok and isinstance(plan, dict):
            checks["plan_valid_json"] = True
            has_keys = ("selected_mentors" in plan and "phases" in plan and "cadence" in plan)
            if has_keys and isinstance(plan.get("selected_mentors"), list) and isinstance(plan.get("phases"), dict) and isinstance(plan.get("cadence"), str):
                checks["plan_has_required_keys"] = True

                # phases exact keys
                phases = plan.get("phases", {})
                if set(phases.keys()) == {"identify", "engage", "ask", "follow_up"}:
                    checks["phases_exact_keys"] = True

                # cadence includes "month"
                cadence = plan.get("cadence", "")
                if isinstance(cadence, str) and ("month" in cadence.lower()):
                    checks["cadence_mentions_month"] = True

                # selected_mentors count >= 3
                selected_mentors = plan.get("selected_mentors", [])
                if isinstance(selected_mentors, list) and len(selected_mentors) >= 3:
                    checks["selected_mentors_count_ok"] = True

                # per mentor fields present
                required_fields = {"name", "reason", "engagement_strategy", "first_ask"}
                fields_ok = True
                for m in selected_mentors:
                    if not isinstance(m, dict):
                        fields_ok = False
                        break
                    if not required_fields.issubset(m.keys()):
                        fields_ok = False
                        break
                    # minimal type checks
                    if not all(isinstance(m.get(k), str) for k in ("name", "reason", "engagement_strategy", "first_ask")):
                        fields_ok = False
                        break
                if fields_ok and len(selected_mentors) >= 1:
                    checks["per_mentor_fields_present"] = True

                # Validate filters and strategies
                allowed_strategies = {
                    "follow_up_from_event",
                    "engage_with_content",
                    "ask_about_specific_problem_at_work",
                    "cold_specific_question",
                }
                strategies_valid = True
                names_ok = True
                filters_ok = True
                strategy_mapping_ok = True

                for m in selected_mentors:
                    name = (m.get("name") or "").strip()
                    strat = (m.get("engagement_strategy") or "").strip()
                    if strat not in allowed_strategies:
                        strategies_valid = False
                    # Name must exist in CSV
                    if name not in mentors_by_name:
                        names_ok = False
                        filters_ok = False
                        strategy_mapping_ok = False
                        continue
                    data = mentors_by_name[name]
                    # Check filters: 2 <= steps_ahead <= 5, accessibility in {"medium","high"}, celebrity == "no"
                    steps = data.get("steps_ahead")
                    accessibility = data.get("accessibility", "")
                    celebrity = data.get("celebrity", "")
                    if not (isinstance(steps, int) and 2 <= steps <= 5):
                        filters_ok = False
                    if accessibility not in {"medium", "high"}:
                        filters_ok = False
                    if celebrity != "no":
                        filters_ok = False
                    # Compute expected engagement strategy by rule
                    if data.get("met_at_event") == "yes":
                        expected = "follow_up_from_event"
                    elif data.get("creates_content") == "yes":
                        expected = "engage_with_content"
                    elif data.get("works_at_same_company") == "yes":
                        expected = "ask_about_specific_problem_at_work"
                    else:
                        expected = "cold_specific_question"
                    if strat != expected:
                        strategy_mapping_ok = False

                if strategies_valid:
                    checks["engagement_strategy_valid_values"] = True
                if names_ok and filters_ok:
                    checks["selected_mentors_meet_filters"] = True
                if strategy_mapping_ok and strategies_valid and names_ok:
                    checks["engagement_strategy_matches_attributes"] = True

    # 2) Outreach messages checks
    if os.path.isfile(outreach_path):
        checks["outreach_exists"] = True
        content = read_text(outreach_path)
        # Only evaluate constraints if we have selected mentors from plan
        if checks["plan_valid_json"] and isinstance(selected_mentors, list) and len(selected_mentors) > 0:
            blocks = split_blocks(content)
            # For each selected mentor, find a block satisfying all criteria
            all_ok = True
            for m in selected_mentors:
                name = (m.get("name") or "").strip()
                found = False
                for blk in blocks:
                    if (name in blk and
                        ("15 minutes" in blk or "20 minutes" in blk) and
                        ("IC vs manager" in blk) and
                        ("report back" in blk)):
                        found = True
                        break
                if not found:
                    all_ok = False
                    break
            if all_ok:
                checks["outreach_per_mentor_constraints"] = True

    # 3) Coffee meeting agenda
    if os.path.isfile(agenda_path):
        checks["agenda_exists"] = True
        agenda_text = read_text(agenda_path)
        lines = agenda_text.splitlines()
        # Find first non-empty line as header
        header_line = None
        for ln in lines:
            if ln.strip() != "":
                header_line = ln.strip()
                break
        bullets = [ln for ln in lines if ln.startswith("- ")]
        if header_line == "Coffee Meeting Agenda" and len(bullets) >= 3:
            checks["agenda_header_and_bullets"] = True

    # 4) Follow-up tracker
    if os.path.isfile(tracker_path):
        checks["tracker_exists"] = True
        try:
            with open(tracker_path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["mentor_name", "date_contacted", "advice_summary", "follow_up_date", "outcome"]
                if header == expected_header:
                    checks["tracker_header_exact"] = True
                    data_rows = rows[1:]
                    # Count non-empty data rows
                    non_empty = [r for r in data_rows if any((cell or "").strip() != "" for cell in r)]
                    # Must be at least as many as count of selected_mentors
                    count_needed = len(selected_mentors) if isinstance(selected_mentors, list) else 0
                    if len(non_empty) >= count_needed and count_needed > 0:
                        checks["tracker_rows_count_ok"] = True
        except Exception:
            pass

    # Global banned phrase check: only evaluate if at least one required file exists
    required_exist = any(os.path.isfile(p) for p in [plan_path, outreach_path, agenda_path, tracker_path])
    checks["no_banned_phrase"] = scan_banned_phrase(output_dir, required_exist)

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    # Ensure no-op baseline: if output dir missing or no required files, reward must be 0.0
    if not required_exist:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()