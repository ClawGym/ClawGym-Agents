import json
import os
import re
import sys
from collections import OrderedDict

def read_file_safe(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = OrderedDict()
    # File existence checks
    checks["file_daily_log_exists"] = False
    checks["file_handoff_exists"] = False
    checks["file_visit_prep_exists"] = False
    checks["file_alerts_exists"] = False
    checks["all_required_files_present"] = False

    # Unit/timestamp/global checks
    checks["no_oz_substring"] = False
    checks["times_count_ge_3"] = False

    # daily_log.md content checks
    checks["daily_log_has_total_intake_ml"] = False
    checks["daily_log_has_wet_diapers_count"] = False
    checks["daily_log_has_dirty_diapers_count"] = False

    # handoff.md labeled sections
    checks["handoff_has_current_state"] = False
    checks["handoff_has_last_major_events"] = False
    checks["handoff_has_different_from_baseline"] = False
    checks["handoff_has_next_actions"] = False
    checks["handoff_has_escalation_watch"] = False

    # visit_prep.md labeled sections
    checks["visit_prep_has_header"] = False
    checks["visit_prep_has_baby_stage"] = False
    checks["visit_prep_has_main_concern"] = False
    checks["visit_prep_has_started"] = False
    checks["visit_prep_has_baseline_vs_now"] = False
    checks["visit_prep_has_feed_change"] = False
    checks["visit_prep_has_sleep_change"] = False
    checks["visit_prep_has_diaper_output_change"] = False
    checks["visit_prep_has_temp_or_symptom_timeline"] = False
    checks["visit_prep_has_meds_or_care_actions"] = False
    checks["visit_prep_has_alert_triggers_observed"] = False
    checks["visit_prep_has_top_questions"] = False

    # alerts.md checks
    checks["alerts_has_alert_heading"] = False
    checks["alerts_has_observed_facts"] = False
    checks["alerts_has_action_advised"] = False
    checks["alerts_has_outcome"] = False
    checks["alerts_has_followup_plan"] = False

    # Paths
    daily_log_path = os.path.join(output_dir, "daily_log.md")
    handoff_path = os.path.join(output_dir, "handoff.md")
    visit_prep_path = os.path.join(output_dir, "visit_prep.md")
    alerts_path = os.path.join(output_dir, "alerts.md")

    # Existence checks
    daily_exists = os.path.isfile(daily_log_path)
    handoff_exists = os.path.isfile(handoff_path)
    visit_prep_exists = os.path.isfile(visit_prep_path)
    alerts_exists = os.path.isfile(alerts_path)

    checks["file_daily_log_exists"] = daily_exists
    checks["file_handoff_exists"] = handoff_exists
    checks["file_visit_prep_exists"] = visit_prep_exists
    checks["file_alerts_exists"] = alerts_exists

    all_present = daily_exists and handoff_exists and visit_prep_exists and alerts_exists
    checks["all_required_files_present"] = all_present

    daily_text = read_file_safe(daily_log_path) if daily_exists else ""
    handoff_text = read_file_safe(handoff_path) if handoff_exists else ""
    visit_prep_text = read_file_safe(visit_prep_path) if visit_prep_exists else ""
    alerts_text = read_file_safe(alerts_path) if alerts_exists else ""

    # Content checks for daily_log.md (only if file exists)
    if daily_exists:
        # "Total intake today:" followed by a number and "mL"
        if re.search(r"Total intake today:\s*\d+(?:\.\d+)?\s*mL", daily_text):
            checks["daily_log_has_total_intake_ml"] = True
        # "Wet diapers today:" followed by a number
        if re.search(r"Wet diapers today:\s*\d+", daily_text):
            checks["daily_log_has_wet_diapers_count"] = True
        # "Dirty diapers today:" followed by a number
        if re.search(r"Dirty diapers today:\s*\d+", daily_text):
            checks["daily_log_has_dirty_diapers_count"] = True

    # Content checks for handoff.md (only if file exists)
    if handoff_exists:
        if re.search(r"^Current state:", handoff_text, flags=re.MULTILINE):
            checks["handoff_has_current_state"] = True
        if re.search(r"^Last major events:", handoff_text, flags=re.MULTILINE):
            checks["handoff_has_last_major_events"] = True
        if re.search(r"^Different from baseline:", handoff_text, flags=re.MULTILINE):
            checks["handoff_has_different_from_baseline"] = True
        if re.search(r"^Next actions:", handoff_text, flags=re.MULTILINE):
            checks["handoff_has_next_actions"] = True
        if re.search(r"^Escalation watch:", handoff_text, flags=re.MULTILINE):
            checks["handoff_has_escalation_watch"] = True

    # Content checks for visit_prep.md (only if file exists)
    if visit_prep_exists:
        if re.search(r"^# Pediatric Summary", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_header"] = True
        if re.search(r"^Baby stage:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_baby_stage"] = True
        if re.search(r"^Main concern:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_main_concern"] = True
        if re.search(r"^Started:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_started"] = True
        if re.search(r"^Baseline versus now:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_baseline_vs_now"] = True
        if re.search(r"^Feed change:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_feed_change"] = True
        if re.search(r"^Sleep change:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_sleep_change"] = True
        if re.search(r"^Diaper/output change:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_diaper_output_change"] = True
        if re.search(r"^Temperature or symptom timeline:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_temp_or_symptom_timeline"] = True
        if re.search(r"^Medications or care actions tried:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_meds_or_care_actions"] = True
        if re.search(r"^Red or amber triggers observed:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_alert_triggers_observed"] = True
        if re.search(r"^Top questions:", visit_prep_text, flags=re.MULTILINE):
            checks["visit_prep_has_top_questions"] = True

    # Content checks for alerts.md (only if file exists)
    if alerts_exists:
        if ("Red Alert" in alerts_text) or ("Amber Alert" in alerts_text):
            checks["alerts_has_alert_heading"] = True
        if "Observed facts:" in alerts_text:
            checks["alerts_has_observed_facts"] = True
        if "Action advised:" in alerts_text:
            checks["alerts_has_action_advised"] = True
        if "Outcome:" in alerts_text:
            checks["alerts_has_outcome"] = True
        if "Follow-up plan:" in alerts_text:
            checks["alerts_has_followup_plan"] = True

    # Global checks requiring all files to be present
    if all_present:
        combined = "\n".join([daily_text, handoff_text, visit_prep_text, alerts_text])
        # No "oz" substring anywhere (case-insensitive)
        if "oz" not in combined.lower():
            checks["no_oz_substring"] = True
        # At least three occurrences of time pattern \b\d{2}:\d{2}\b
        times = re.findall(r"\b\d{2}:\d{2}\b", combined)
        if len(times) >= 3:
            checks["times_count_ge_3"] = True

    # Compute reward
    # If required artifacts are missing, reward must be exactly 0.0
    if not all_present:
        reward_value = 0.0
    else:
        # Fraction of checks passed (including existence checks)
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward_value = passed / total if total > 0 else 0.0

    # Output JSON with "reward" first
    result = OrderedDict()
    result["reward"] = float(round(reward_value, 6))
    for k, v in checks.items():
        result[k] = bool(v)

    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()