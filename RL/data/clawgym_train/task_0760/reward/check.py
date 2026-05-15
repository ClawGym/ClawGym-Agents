import json
import os
import sys
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return [line.rstrip("\n") for line in f]
    except Exception:
        return []

def parse_csv_header_and_rows(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            header = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return [], []

def str_to_bool(val):
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in {"true", "yes", "1", "y", "t"}

def safe_float(x):
    try:
        if isinstance(x, bool):
            return float(int(x))
        return float(x)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")
    ops_dir = os.path.join(output_dir, "ops")

    # Paths
    opening_path = os.path.join(ops_dir, "opening_closing.md")
    cycle_counts_path = os.path.join(ops_dir, "cycle_counts.csv")
    staffing_path = os.path.join(ops_dir, "staffing_schedule.csv")
    promo_plan_path = os.path.join(ops_dir, "promo_plan.md")
    weekly_review_path = os.path.join(ops_dir, "weekly_review.md")
    priorities_path = os.path.join(ops_dir, "next_week_priorities.json")
    metrics_summary_path = os.path.join(ops_dir, "metrics_summary.json")

    checks = {}

    # Existence checks
    files_exist = {
        "files_exist_opening_closing": os.path.isfile(opening_path),
        "files_exist_cycle_counts": os.path.isfile(cycle_counts_path),
        "files_exist_staffing_schedule": os.path.isfile(staffing_path),
        "files_exist_promo_plan": os.path.isfile(promo_plan_path),
        "files_exist_weekly_review": os.path.isfile(weekly_review_path),
        "files_exist_next_week_priorities": os.path.isfile(priorities_path),
        "files_exist_metrics_summary": os.path.isfile(metrics_summary_path),
    }
    checks.update(files_exist)
    checks["all_required_files_present"] = all(files_exist.values())

    # Initialize all artifact-dependent checks to False by default
    # opening_closing.md content checks
    checks["opening_contains_cash_float"] = False
    checks["opening_contains_discrepancy"] = False
    checks["opening_contains_replenish_fast_movers"] = False
    checks["opening_contains_incident_log"] = False
    checks["opening_actionable_checklist"] = False

    if checks["files_exist_opening_closing"]:
        text = read_text(opening_path).lower()
        lines = read_lines(opening_path)
        checks["opening_contains_cash_float"] = "cash float" in text
        checks["opening_contains_discrepancy"] = "discrepancy" in text
        checks["opening_contains_replenish_fast_movers"] = "replenish fast movers" in text
        checks["opening_contains_incident_log"] = "incident log" in text
        # actionable routine: multiple checklist-like lines
        checklist_count = 0
        for ln in lines:
            s = ln.strip()
            if s.startswith("- ") or s.startswith("* ") or re.match(r"^\d+\.\s", s):
                checklist_count += 1
        checks["opening_actionable_checklist"] = checklist_count >= 3

    # cycle_counts.csv checks
    checks["cycle_header_ok"] = False
    checks["cycle_has_daily"] = False
    checks["cycle_has_several_per_week"] = False
    checks["cycle_fast_mover_rule"] = False
    checks["cycle_high_value_rule"] = False
    checks["cycle_high_shrink_rule"] = False

    if checks["files_exist_cycle_counts"]:
        header, rows = parse_csv_header_and_rows(cycle_counts_path)
        required_cols = {"sku", "category", "count_frequency", "rationale"}
        normalized_header = {h.strip().lower() for h in header}
        checks["cycle_header_ok"] = (normalized_header == required_cols)

        # Count frequencies presence
        daily_present = False
        spw_present = False
        fast_mover_rule_ok = True  # assume true, invalidate on violation
        high_value_rule_ok = True
        high_shrink_rule_ok = True

        for row in rows:
            freq = (row.get("count_frequency") or row.get("COUNT_FREQUENCY") or "").strip().lower()
            rationale = (row.get("rationale") or row.get("RATIONALE") or "").strip().lower()
            if freq == "daily":
                daily_present = True
            if freq == "several_per_week":
                spw_present = True

            if "fast mover" in rationale and freq != "daily":
                fast_mover_rule_ok = False
            if ("high value" in rationale) and freq != "several_per_week":
                high_value_rule_ok = False
            if ("high shrink" in rationale) and freq != "several_per_week":
                high_shrink_rule_ok = False

        checks["cycle_has_daily"] = daily_present
        checks["cycle_has_several_per_week"] = spw_present
        checks["cycle_fast_mover_rule"] = fast_mover_rule_ok and len(rows) > 0
        checks["cycle_high_value_rule"] = high_value_rule_ok and len(rows) > 0
        checks["cycle_high_shrink_rule"] = high_shrink_rule_ok and len(rows) > 0

    # staffing_schedule.csv checks
    checks["staffing_header_ok"] = False
    checks["staffing_peak_rows_exist"] = False
    checks["staffing_peak_staffing_ok"] = False
    checks["staffing_non_peak_staffing_ok"] = False
    checks["staffing_lead_present"] = False

    if checks["files_exist_staffing_schedule"]:
        header, rows = parse_csv_header_and_rows(staffing_path)
        required_cols_staff = {"day", "hour", "is_peak", "staff_count", "lead_on_duty", "role_focus"}
        normalized_header_staff = {h.strip().lower() for h in header}
        checks["staffing_header_ok"] = (normalized_header_staff == required_cols_staff)

        peak_rows = []
        non_peak_rows = []
        lead_present = False
        peak_ok = True
        non_peak_ok = True

        for row in rows:
            is_peak_val = row.get("is_peak")
            if is_peak_val is None:
                # Try alternative case
                is_peak_val = row.get("IS_PEAK")
            is_peak_bool = str_to_bool(is_peak_val)
            staff_count_raw = row.get("staff_count") or row.get("STAFF_COUNT")
            staff_count_num = None
            try:
                staff_count_num = int(float(staff_count_raw)) if staff_count_raw is not None else None
            except Exception:
                staff_count_num = None

            lead = row.get("lead_on_duty") or row.get("LEAD_ON_DUTY") or ""
            if str(lead).strip() != "":
                lead_present = True

            if is_peak_bool:
                peak_rows.append(row)
                if staff_count_num is None or staff_count_num < 3:
                    peak_ok = False
            else:
                non_peak_rows.append(row)
                if staff_count_num is None or staff_count_num < 1:
                    non_peak_ok = False

        checks["staffing_peak_rows_exist"] = len(peak_rows) > 0
        checks["staffing_peak_staffing_ok"] = peak_ok and len(rows) > 0
        checks["staffing_non_peak_staffing_ok"] = non_peak_ok and len(rows) > 0
        checks["staffing_lead_present"] = lead_present

    # promo_plan.md checks
    checks["promo_has_goal"] = False
    checks["promo_has_target_items"] = False
    checks["promo_has_floor_placement"] = False
    checks["promo_has_signage_checklist"] = False
    checks["promo_has_owner"] = False
    checks["promo_has_end_date"] = False
    checks["promo_has_success_metric"] = False

    if checks["files_exist_promo_plan"]:
        lines = read_lines(promo_plan_path)
        def has_prefix(prefix):
            pfx = prefix.lower()
            for ln in lines:
                if ln.strip().lower().startswith(pfx):
                    return True
            return False

        checks["promo_has_goal"] = has_prefix("Goal:")
        checks["promo_has_target_items"] = has_prefix("Target Items:")
        checks["promo_has_floor_placement"] = has_prefix("Floor Placement:")
        checks["promo_has_signage_checklist"] = has_prefix("Signage Checklist:")
        checks["promo_has_owner"] = has_prefix("Owner:")
        checks["promo_has_end_date"] = has_prefix("End Date:")
        checks["promo_has_success_metric"] = has_prefix("Success Metric:")

    # weekly_review.md checks
    checks["weekly_has_improved_section"] = False
    checks["weekly_has_deteriorated_section"] = False
    checks["weekly_mentions_conversion"] = False
    checks["weekly_mentions_average_ticket"] = False
    checks["weekly_mentions_margin"] = False
    checks["weekly_mentions_labor_hours"] = False
    checks["weekly_has_next_step_verb"] = False

    if checks["files_exist_weekly_review"]:
        text = read_text(weekly_review_path).lower()
        checks["weekly_has_improved_section"] = "what improved?" in text
        checks["weekly_has_deteriorated_section"] = "what deteriorated?" in text
        checks["weekly_mentions_conversion"] = "conversion" in text
        checks["weekly_mentions_average_ticket"] = "average ticket" in text
        checks["weekly_mentions_margin"] = "margin" in text
        checks["weekly_mentions_labor_hours"] = "labor hours" in text
        # look for clear next step action verbs
        action_verbs = ["assign", "schedule", "count", "replenish"]
        checks["weekly_has_next_step_verb"] = any(verb in text for verb in action_verbs)

    # next_week_priorities.json checks
    checks["priorities_json_valid"] = False
    checks["priorities_types_ok"] = False
    checks["priorities_metrics_contains_key"] = False
    checks["priorities_single_focus_with_action"] = False

    if checks["files_exist_next_week_priorities"]:
        try:
            with open(priorities_path, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            checks["priorities_json_valid"] = True

            # Type checks and required keys
            required_keys = ["primary_focus", "owner", "metrics", "actions", "due_date", "success_metric"]
            has_keys = all(k in data for k in required_keys)
            types_ok = (
                isinstance(data.get("primary_focus"), str) and
                isinstance(data.get("owner"), str) and
                isinstance(data.get("metrics"), list) and
                isinstance(data.get("actions"), list) and
                isinstance(data.get("due_date"), str) and
                isinstance(data.get("success_metric"), str)
            ) if has_keys else False

            # due date format
            due_ok = False
            if types_ok:
                due_ok = re.match(r"^\d{4}-\d{2}-\d{2}$", data.get("due_date", "")) is not None

            checks["priorities_types_ok"] = has_keys and types_ok and due_ok

            # metrics contains at least one of the required tokens
            metrics_list = data.get("metrics") if isinstance(data.get("metrics"), list) else []
            lower_metrics = [str(m).lower() for m in metrics_list]
            required_any = {"conversion", "stock-outs", "gross margin", "labor hours"}
            checks["priorities_metrics_contains_key"] = any(
                any(req in m for req in required_any) for m in lower_metrics
            )

            # single primary focus (non-empty) and at least one action
            pf = data.get("primary_focus")
            actions = data.get("actions") if isinstance(data.get("actions"), list) else []
            checks["priorities_single_focus_with_action"] = isinstance(pf, str) and pf.strip() != "" and len(actions) >= 1

        except Exception:
            # already initialized to False
            pass

    # metrics_summary.json checks
    checks["metrics_json_valid"] = False
    checks["metrics_fields_numeric"] = False
    checks["metrics_conversion_matches"] = False

    if checks["files_exist_metrics_summary"]:
        try:
            with open(metrics_summary_path, "r", encoding="utf-8", errors="ignore") as f:
                m = json.load(f)
            checks["metrics_json_valid"] = True

            numeric_fields = ["sales", "traffic", "conversion", "average_ticket", "gross_margin", "labor_hours", "stock_outs", "shrink"]
            types_ok = True
            values = {}
            for k in numeric_fields:
                if k not in m:
                    types_ok = False
                    break
                val = m.get(k)
                num = safe_float(val)
                if num is None:
                    types_ok = False
                    break
                values[k] = float(num)
            checks["metrics_fields_numeric"] = types_ok

            if types_ok:
                sales = values["sales"]
                traffic = values["traffic"]
                conv = values["conversion"]
                if traffic == 0:
                    expected_conv = 0.0
                else:
                    expected_conv = sales / traffic
                checks["metrics_conversion_matches"] = abs(conv - expected_conv) <= 0.0001

        except Exception:
            # remains False
            pass

    # Compute reward
    # All-or-nothing gating on required files
    artifact_checks = [k for k in checks.keys() if k not in ("all_required_files_present",)]
    total_points = len(artifact_checks)
    passed_points = sum(1 for k in artifact_checks if checks[k])

    if not checks["all_required_files_present"]:
        reward = 0.0
    else:
        # avoid division by zero
        reward = (passed_points / total_points) if total_points > 0 else 0.0
        # Clamp to [0,1]
        reward = max(0.0, min(1.0, reward))

    # Prepare output JSON with "reward" first
    out = {"reward": reward}
    # Add all checks in a stable order
    for k in sorted(checks.keys()):
        out[k] = bool(checks[k])

    print(json.dumps(out))

if __name__ == "__main__":
    main()