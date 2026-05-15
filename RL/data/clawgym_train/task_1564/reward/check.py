import json
import os
import sys
import csv
from datetime import datetime
from collections import Counter

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_jsonl_file(path):
    objs = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    objs.append(obj)
                except Exception:
                    return None
        return objs
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def to_counter_of_objs(objs):
    # Convert dicts into deterministic JSON strings for multiset comparison
    ser = []
    for o in objs:
        try:
            ser.append(json.dumps(o, sort_keys=True, separators=(",", ":")))
        except Exception:
            ser.append(str(o))
    return Counter(ser)

def is_iso8601(s):
    if not isinstance(s, str) or not s:
        return False
    try:
        # Handle trailing Z as UTC
        ss = s.replace("Z", "+00:00") if s.endswith("Z") else s
        datetime.fromisoformat(ss)
        return True
    except Exception:
        return False

def case_insensitive_contains(haystack, needle):
    return needle.lower() in haystack.lower()

def safe_float(s):
    try:
        return float(s)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "estimate_json_valid": False,
        "estimate_has_scenarios": False,
        "estimate_scenarios_fields": False,
        "decision_matrix_ok": False,
        "roi_json_valid": False,
        "compliance_csv_header_ok": False,
        "compliance_csv_frameworks_ok": False,
        "compliance_csv_total_row_ok": False,
        "compliance_csv_numbers_ok": False,
        "assumptions_guard_ok": False,
        "action_check_result_ok": False,
        "action_log_ok": False,
    }

    # Paths
    estimate_path = os.path.join(output_dir, "estimate.json")
    decision_matrix_path = os.path.join(output_dir, "decision_matrix.md")
    roi_path = os.path.join(output_dir, "roi.json")
    compliance_csv_path = os.path.join(output_dir, "compliance_budget.csv")
    guard_md_path = os.path.join(output_dir, "assumptions_guard.md")
    check_result_path = os.path.join(output_dir, "check_result.txt")
    actions_out_path = os.path.join(output_dir, ".action-guard", "actions.jsonl")

    usage_assumptions_path = os.path.join(input_dir, "usage_assumptions.json")
    existing_actions_path = os.path.join(input_dir, "existing_actions.jsonl")

    # 1) estimate.json checks
    estimate_obj = parse_json_file(estimate_path)
    if isinstance(estimate_obj, dict):
        checks["estimate_json_valid"] = True
        scenarios = estimate_obj.get("scenarios")
        if isinstance(scenarios, dict) and "diy_single_agent" in scenarios and "managed_service" in scenarios:
            checks["estimate_has_scenarios"] = True

            required_monthly_keys = ["compute", "llm_api", "storage", "monitoring", "engineering", "total_monthly"]
            scenarios_ok = True
            for scen_key in ["diy_single_agent", "managed_service"]:
                scen = scenarios.get(scen_key, {})
                if not isinstance(scen, dict):
                    scenarios_ok = False
                    break

                # Monthly breakdown may be under "monthly" or directly in scenario
                monthly_container = scen.get("monthly")
                if isinstance(monthly_container, dict):
                    monthly = monthly_container
                else:
                    monthly = scen

                # Check required monthly numeric fields
                for k in required_monthly_keys:
                    v = monthly.get(k, None)
                    if not is_number(v):
                        scenarios_ok = False
                        break
                if not scenarios_ok:
                    break

                # setup_one_time numeric (prefer scenario-level but accept if in monthly for leniency)
                setup_val = scen.get("setup_one_time", monthly.get("setup_one_time", None))
                if not is_number(setup_val):
                    scenarios_ok = False
                    break

                # total_12_months numeric (intended at scenario level; accept if present anywhere)
                t12 = scen.get("total_12_months", monthly.get("total_12_months", None))
                if not is_number(t12):
                    scenarios_ok = False
                    break

            if scenarios_ok:
                checks["estimate_scenarios_fields"] = True

    # 2) decision_matrix.md checks
    dm_text = read_text(decision_matrix_path)
    if isinstance(dm_text, str) and dm_text.strip():
        required_factors = [
            "Time to deploy",
            "Monthly cost (single)",
            "Engineering dependency",
            "Customization",
            "Support/SLA",
            "Scaling",
            "Risk",
        ]
        has_all_factors = all(case_insensitive_contains(dm_text, f) for f in required_factors)
        has_alternatives = case_insensitive_contains(dm_text, "Build In-House") and case_insensitive_contains(dm_text, "Managed Service")
        if has_all_factors and has_alternatives:
            checks["decision_matrix_ok"] = True

    # 3) roi.json checks
    roi_obj = parse_json_file(roi_path)
    usage_obj = parse_json_file(usage_assumptions_path)

    if isinstance(roi_obj, dict) and isinstance(usage_obj, dict):
        mv = roi_obj.get("monthly_value")
        mc = roi_obj.get("monthly_cost")
        rp = roi_obj.get("roi_percent")
        notes = roi_obj.get("notes")
        fields_ok = is_number(mv) and is_number(mc) and is_number(rp) and isinstance(notes, str) and notes.strip() != ""
        if fields_ok:
            # Recompute monthly_value
            try:
                hspw = float(usage_obj.get("hours_saved_per_week"))
                hourly_cost = float(usage_obj.get("hourly_cost"))
                erm = float(usage_obj.get("error_reduction_per_month"))
                cpe = float(usage_obj.get("cost_per_error"))
                sirm = float(usage_obj.get("speed_improvement_revenue_per_month"))
                recomputed_mv = (hspw * hourly_cost * 4.0) + (erm * cpe) + sirm
                # Tolerance for floating-point rounding
                mv_close = abs(float(mv) - recomputed_mv) <= 0.5
                mc_ok = float(mc) == 1500.0
                rp_ok = 450.0 <= float(rp) <= 460.0
                if mv_close and mc_ok and rp_ok:
                    checks["roi_json_valid"] = True
            except Exception:
                pass

    # 4) compliance_budget.csv checks
    if os.path.isfile(compliance_csv_path):
        try:
            with open(compliance_csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["framework", "cost_type", "monthly_cost", "one_time_cost", "notes"]
                checks["compliance_csv_header_ok"] = header == expected_header

                frameworks_seen = set()
                total_row_present = False
                numbers_ok = True

                for r in rows[1:]:
                    if not r or len(r) < 5:
                        numbers_ok = False
                        break
                    framework_cell = r[0] if len(r) > 0 else ""
                    cost_type_cell = r[1] if len(r) > 1 else ""
                    monthly_cell = r[2] if len(r) > 2 else ""
                    one_time_cell = r[3] if len(r) > 3 else ""

                    # Framework checks (case-insensitive substring)
                    lc_fw = (framework_cell or "").lower()
                    if "soc 2" in lc_fw:
                        frameworks_seen.add("soc2")
                    if "iso 27001" in lc_fw:
                        frameworks_seen.add("iso27001")
                    if "gdpr" in lc_fw:
                        frameworks_seen.add("gdpr")

                    # TOTAL row check
                    if (cost_type_cell or "").strip().lower() == "total":
                        total_row_present = True

                    # Numeric parsing
                    if safe_float(monthly_cell) is None or safe_float(one_time_cell) is None:
                        numbers_ok = False
                        break

                if {"soc2", "iso27001", "gdpr"}.issubset(frameworks_seen):
                    checks["compliance_csv_frameworks_ok"] = True
                if total_row_present:
                    checks["compliance_csv_total_row_ok"] = True
                if numbers_ok:
                    checks["compliance_csv_numbers_ok"] = True
        except Exception:
            pass

    # 5) assumptions_guard.md checks
    guard_text = read_text(guard_md_path)
    if isinstance(guard_text, str) and guard_text.strip():
        trap_names = [
            "Confirmation Bias",
            "Recency Bias",
            "Anchoring",
            "Sunk Cost",
            "Availability Heuristic",
            "Narrative Fallacy",
            "Clustering Illusion",
            "Einstellung Effect",
            "Survivorship Bias",
            "Occam's Broom",
            "Fundamental Attribution Error",
            "XY Problem",
        ]
        found = set()
        for t in trap_names:
            if case_insensitive_contains(guard_text, t):
                found.add(t.lower())
        words_required = ["action", "counter-action", "intervention"]
        has_action_word = any(case_insensitive_contains(guard_text, w) for w in words_required)
        if len(found) >= 3 and has_action_word:
            checks["assumptions_guard_ok"] = True

    # 6) Action dedup check & log
    existing_actions = parse_jsonl_file(existing_actions_path)
    output_actions = parse_jsonl_file(actions_out_path)
    check_result_text = read_text(check_result_path)

    # Validate check_result.txt is exactly "skip" or "proceed"
    cr_valid_str = isinstance(check_result_text, str)
    cr_value = (check_result_text or "").strip() if cr_valid_str else ""
    cr_is_valid = cr_value in ("skip", "proceed")

    input_has_existing = False
    if isinstance(existing_actions, list):
        input_has_existing = any(
            isinstance(a, dict)
            and a.get("type") == "proposal"
            and a.get("target") == "proposal:acme-rfp-2026"
            for a in existing_actions
        )

    # action_check_result_ok: check consistency between input and check_result
    if cr_is_valid:
        if input_has_existing and cr_value == "skip":
            checks["action_check_result_ok"] = True
        elif (not input_has_existing) and cr_value == "proceed":
            checks["action_check_result_ok"] = True

    # action_log_ok: validate actions.jsonl content per rules
    def validate_actions_skip_case():
        # Must mirror input; no extra lines
        if not isinstance(existing_actions, list) or not isinstance(output_actions, list):
            return False
        # Counts must be equal
        if len(existing_actions) != len(output_actions):
            return False
        # Multiset must match
        return to_counter_of_objs(existing_actions) == to_counter_of_objs(output_actions)

    def validate_actions_proceed_case():
        if not isinstance(existing_actions, list) or not isinstance(output_actions, list):
            return False
        # Must include all input lines plus exactly one appended record
        if len(output_actions) != len(existing_actions) + 1:
            return False
        # Count of matching proposal record must be exactly one more than input
        input_match_count = sum(
            1
            for a in existing_actions
            if isinstance(a, dict)
            and a.get("type") == "proposal"
            and a.get("target") == "proposal:acme-rfp-2026"
        )
        output_match_objs = [
            a
            for a in output_actions
            if isinstance(a, dict)
            and a.get("type") == "proposal"
            and a.get("target") == "proposal:acme-rfp-2026"
        ]
        if len(output_match_objs) != input_match_count + 1:
            return False
        # At least one of the output match objects must have ts ISO 8601 and a non-empty note
        has_valid_new = False
        for a in output_match_objs:
            ts = a.get("ts")
            note = a.get("note")
            if is_iso8601(ts) and isinstance(note, str) and note.strip() != "":
                has_valid_new = True
                break
        if not has_valid_new:
            return False
        # Ensure all original input actions are contained within output (as a multiset subset)
        in_counter = to_counter_of_objs(existing_actions)
        out_counter = to_counter_of_objs(output_actions)
        # Every input occurrence must be less than or equal to output occurrences
        for k, v in in_counter.items():
            if out_counter.get(k, 0) < v:
                return False
        return True

    if cr_is_valid and isinstance(output_actions, list) and isinstance(existing_actions, list):
        if cr_value == "skip" and input_has_existing:
            if validate_actions_skip_case():
                checks["action_log_ok"] = True
        elif cr_value == "proceed" and (not input_has_existing):
            if validate_actions_proceed_case():
                checks["action_log_ok"] = True

    # Compute reward as average of True checks; if none, reward 0.0
    total_checks = len(checks)
    true_count = sum(1 for v in checks.values() if v)
    reward = (true_count / total_checks) if total_checks > 0 and true_count > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()