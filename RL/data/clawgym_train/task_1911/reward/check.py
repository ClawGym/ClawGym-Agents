import json
import os
import sys
import re

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Plan.json file and structure
        "plan_exists": False,
        "plan_valid_json": False,
        "plan_required_keys_present": False,
        "plan_hypothesis_nonempty": False,
        "plan_codified_rules_structure": False,
        "plan_exit_numbers_valid": False,
        "plan_position_sizing_valid": False,
        "plan_backtest_periods_constraints": False,
        "plan_stress_tests_exact": False,
        "plan_execution_friction_pessimistic": False,
        "plan_sample_size_thresholds": False,
        "plan_year_by_year_true": False,
        "plan_out_of_sample_walk_forward": False,
        "plan_bias_checks_true": False,
        "plan_inputs_used_exact": False,
        # Report.md file content checks
        "report_exists": False,
        "report_word_count_400": False,
        "report_contains_plateaus_not_peaks": False,
        "report_contains_walk_forward": False,
        "report_contains_out_of_sample": False,
        "report_contains_year_by_year": False,
        "report_mentions_three_failure_patterns": False,
        "report_mentions_slippage_multipliers": False,
    }

    # Paths
    plan_path = os.path.join(output_dir, "plan.json")
    report_path = os.path.join(output_dir, "report.md")

    # Check for plan.json existence and parse
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan_text = load_text(plan_path)
        if plan_text is not None:
            try:
                plan = json.loads(plan_text)
                checks["plan_valid_json"] = True
            except Exception:
                plan = None
        else:
            plan = None
    else:
        plan = None

    # Validate plan.json structure and fields only if valid JSON
    if checks["plan_valid_json"] and isinstance(plan, dict):
        # Required top-level keys
        required_top_keys = {
            "hypothesis", "codified_rules", "costs", "backtest_periods",
            "stress_tests", "execution_friction", "sample_size",
            "year_by_year_analysis", "out_of_sample", "bias_checks",
            "evaluation_criteria", "inputs_used"
        }
        if required_top_keys.issubset(set(plan.keys())):
            checks["plan_required_keys_present"] = True

        # Hypothesis non-empty string
        hyp = plan.get("hypothesis")
        if isinstance(hyp, str) and hyp.strip():
            checks["plan_hypothesis_nonempty"] = True

        # codified_rules structure
        cr = plan.get("codified_rules")
        if isinstance(cr, dict):
            needed_cr_keys = {"entry", "exit", "position_sizing", "filters", "universe"}
            has_all_cr = needed_cr_keys.issubset(set(cr.keys()))
            # Basic nested structure checks
            entry_ok = isinstance(cr.get("entry"), dict) and \
                       "conditions" in cr["entry"] and "timing" in cr["entry"] and "order_type" in cr["entry"]
            exit_ok = isinstance(cr.get("exit"), dict)
            ps_ok = isinstance(cr.get("position_sizing"), dict)
            filt_ok = isinstance(cr.get("filters"), dict)
            uni_ok = isinstance(cr.get("universe"), str)
            if has_all_cr and entry_ok and exit_ok and ps_ok and filt_ok and uni_ok:
                checks["plan_codified_rules_structure"] = True

            # Exit numbers
            exit_dict = cr.get("exit", {})
            sl = exit_dict.get("stop_loss_pct")
            pt = exit_dict.get("profit_target_pct")
            ted = exit_dict.get("time_exit_days")
            if is_number(sl) and sl > 0 and is_number(pt) and pt > 0 and is_number(ted):
                checks["plan_exit_numbers_valid"] = True

            # Position sizing
            ps = cr.get("position_sizing", {})
            method = ps.get("method")
            r_pct = ps.get("risk_per_trade_pct")
            if method in {"fixed_fraction", "volatility_adjusted", "fixed_dollar"} and is_number(r_pct) and r_pct > 0:
                checks["plan_position_sizing_valid"] = True

        # backtest_periods constraints
        bp = plan.get("backtest_periods")
        if isinstance(bp, dict):
            years = bp.get("years_covered")
            regimes = bp.get("regimes")
            regimes_ok = False
            if isinstance(regimes, list):
                regimes_ok = set(regimes) == {"bull", "bear", "high_volatility", "low_volatility"} and len(regimes) == 4
            if isinstance(years, int) and years >= 5 and regimes_ok:
                checks["plan_backtest_periods_constraints"] = True

        # stress_tests exact arrays and flags
        st = plan.get("stress_tests")
        if isinstance(st, dict):
            sl_mult = st.get("stop_loss_multipliers")
            pt_mult = st.get("profit_target_multipliers")
            time_shift = st.get("entry_exit_time_shift_minutes")
            slip_mult = st.get("slippage_multipliers")
            worst_case = st.get("worst_case_fills")
            rejections = st.get("order_rejections")
            if (isinstance(sl_mult, list) and sl_mult == [0.5, 0.75, 1.0, 1.25, 1.5] and
                isinstance(pt_mult, list) and pt_mult == [0.8, 0.9, 1.0, 1.1, 1.2] and
                isinstance(time_shift, list) and time_shift == [-30, -15, 0, 15, 30] and
                isinstance(slip_mult, list) and slip_mult == [1.5, 2.0] and
                worst_case is True and rejections is True):
                checks["plan_stress_tests_exact"] = True

        # execution_friction pessimistic details
        ef = plan.get("execution_friction")
        if isinstance(ef, dict):
            model = ef.get("model")
            ef_slip = ef.get("slippage_multipliers")
            pf = ef.get("partial_fills")
            has_15 = False
            has_20 = False
            if isinstance(ef_slip, list):
                has_15 = 1.5 in ef_slip
                has_20 = 2.0 in ef_slip
            if model == "pessimistic" and pf is True and has_15 and has_20:
                checks["plan_execution_friction_pessimistic"] = True

        # sample_size thresholds
        ss = plan.get("sample_size")
        if isinstance(ss, dict):
            min_tr = ss.get("min_trades")
            pref_tr = ss.get("preferred_trades")
            if isinstance(min_tr, int) and min_tr >= 100 and isinstance(pref_tr, int) and pref_tr >= 200:
                checks["plan_sample_size_thresholds"] = True

        # year_by_year_analysis
        yby = plan.get("year_by_year_analysis")
        if yby is True:
            checks["plan_year_by_year_true"] = True

        # out_of_sample walk_forward windows
        oos = plan.get("out_of_sample")
        if isinstance(oos, dict):
            method = oos.get("method")
            windows = oos.get("windows")
            has_window = False
            if isinstance(windows, list):
                for w in windows:
                    if isinstance(w, dict) and w.get("train_years") == 3 and w.get("test_years") == 1:
                        has_window = True
                        break
            if method == "walk_forward" and has_window:
                checks["plan_out_of_sample_walk_forward"] = True

        # bias_checks flags all true
        bc = plan.get("bias_checks")
        if isinstance(bc, dict):
            if bc.get("look_ahead") is True and bc.get("survivorship") is True and bc.get("data_snooping") is True:
                checks["plan_bias_checks_true"] = True

        # inputs_used exact list
        iu = plan.get("inputs_used")
        if isinstance(iu, list) and iu == ["input/strategy_draft.md", "input/trade_log_sample.csv", "input/regimes.yaml"]:
            checks["plan_inputs_used_exact"] = True

    # Report checks
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report_text = load_text(report_path)
        if isinstance(report_text, str):
            # Word count
            words = report_text.split()
            if len(words) >= 400:
                checks["report_word_count_400"] = True

            # Phrases and keywords
            if "plateaus not peaks" in report_text:
                checks["report_contains_plateaus_not_peaks"] = True

            lower_text = report_text.lower()
            if "walk-forward" in lower_text:
                checks["report_contains_walk_forward"] = True
            if "out-of-sample" in lower_text:
                checks["report_contains_out_of_sample"] = True
            if "year-by-year" in lower_text:
                checks["report_contains_year_by_year"] = True

            # Failure patterns: require at least three mentioned
            patterns = [
                "parameter sensitivity",
                "regime-specific",
                "slippage sensitivity",
                "sample size",
                "look-ahead bias",
                "over-optimization",
            ]
            count = sum(1 for p in patterns if p in lower_text)
            if count >= 3:
                checks["report_mentions_three_failure_patterns"] = True

            # Slippage multipliers references
            if ("1.5x" in report_text) and ("2.0x" in report_text):
                checks["report_mentions_slippage_multipliers"] = True

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # Enforce no-op baseline: if required artifacts missing, reward must be 0.0
    required_artifacts_present = checks["plan_exists"] and checks["report_exists"]
    if not required_artifacts_present:
        reward = 0.0
    else:
        # Reward as fraction of passed checks
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Clamp reward between 0 and 1
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()