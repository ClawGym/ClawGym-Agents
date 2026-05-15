import json
import os
import sys


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def load_json_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
        non_empty = [ln for ln in lines if ln.strip() != ""]
        objs = []
        for ln in non_empty:
            try:
                objs.append(json.loads(ln))
            except Exception:
                return None, non_empty, "invalid_json_line"
        return objs, non_empty, None
    except Exception as e:
        return None, [], str(e)


def check_config(config_path):
    checks = {
        "config_exists": False,
        "config_valid_json": False,
        "config_agg_method_ok": False,
        "config_overall_threshold_ok": False,
        "config_dimensions_names_exact": False,
        "config_auto_format_headers_true": False,
        "config_auto_required_sections_contains": False,
        "config_auto_required_sections_case_insensitive": False,
        "config_auto_filler_words_ok": False,
        "config_auto_hedge_words_ok": False,
        "config_auto_sycophancy_markers_ok": False,
        "config_auto_response_length_values": False,
        "config_auto_style_consistency_value": False,
        "config_dimensions_wired_sensible": False,
    }

    if not os.path.isfile(config_path):
        return checks

    checks["config_exists"] = True
    cfg, err = load_json_file(config_path)
    if cfg is None:
        return checks
    checks["config_valid_json"] = True

    # AGGREGATE_METHOD
    if isinstance(cfg.get("AGGREGATE_METHOD"), str) and cfg.get("AGGREGATE_METHOD") == "weighted_average":
        checks["config_agg_method_ok"] = True

    # OVERALL_PASS_THRESHOLD
    if is_number(cfg.get("OVERALL_PASS_THRESHOLD")) and float(cfg.get("OVERALL_PASS_THRESHOLD")) == 3.0:
        checks["config_overall_threshold_ok"] = True

    # DIMENSIONS names exact
    dims = cfg.get("DIMENSIONS")
    if isinstance(dims, list):
        names = []
        for d in dims:
            if isinstance(d, dict) and isinstance(d.get("name"), str):
                names.append(d.get("name"))
        target = ["accuracy", "completeness", "tone", "format_compliance", "consistency"]
        if sorted(names) == sorted(target) and len(names) == 5:
            checks["config_dimensions_names_exact"] = True

    # AUTO_CHECKS
    ac = cfg.get("AUTO_CHECKS", {})
    if isinstance(ac, dict):
        # format_structure.expect_headers == true
        fs = ac.get("format_structure", {})
        if isinstance(fs, dict) and fs.get("expect_headers") is True:
            checks["config_auto_format_headers_true"] = True

        # required_sections sections include Summary, Recommendations, Risks (case-insensitive acceptable)
        rs = ac.get("required_sections", {})
        req_ok = False
        rs_case_ok = False
        if isinstance(rs, dict):
            sections = rs.get("sections", [])
            if isinstance(sections, list):
                lower = [str(s).strip().lower() for s in sections if isinstance(s, str)]
                needed = ["summary", "recommendations", "risks"]
                if all(n in lower for n in needed):
                    req_ok = True
            # case-insensitive means case_sensitive false
            if rs.get("case_sensitive") is False:
                rs_case_ok = True
        checks["config_auto_required_sections_contains"] = req_ok
        checks["config_auto_required_sections_case_insensitive"] = rs_case_ok

        # filler_words threshold_per_1000_chars >= 3 and includes words
        fw = ac.get("filler_words", {})
        fw_ok = False
        if isinstance(fw, dict):
            thr = fw.get("threshold_per_1000_chars")
            words = fw.get("words", [])
            if is_number(thr) and float(thr) >= 3 and isinstance(words, list):
                wlower = [str(w).strip().lower() for w in words]
                needed_fw = ["basically", "actually", "literally", "just"]
                if all(n in wlower for n in needed_fw):
                    fw_ok = True
        checks["config_auto_filler_words_ok"] = fw_ok

        # hedge_words threshold_per_1000_chars >= 4 and includes words
        hw = ac.get("hedge_words", {})
        hw_ok = False
        if isinstance(hw, dict):
            thr = hw.get("threshold_per_1000_chars")
            words = hw.get("words", [])
            if is_number(thr) and float(thr) >= 4 and isinstance(words, list):
                wlower = [str(w).strip().lower() for w in words]
                needed_hw = ["might", "perhaps", "i think", "it seems"]
                if all(n in wlower for n in needed_hw):
                    hw_ok = True
        checks["config_auto_hedge_words_ok"] = hw_ok

        # sycophancy markers include
        sy = ac.get("sycophancy", {})
        sy_ok = False
        if isinstance(sy, dict):
            markers = sy.get("markers", [])
            if isinstance(markers, list):
                mlower = [str(m).strip().lower() for m in markers]
                needed_sy = ["great question", "excellent question", "i'm so glad you asked"]
                if all(n in mlower for n in needed_sy):
                    sy_ok = True
        checks["config_auto_sycophancy_markers_ok"] = sy_ok

        # response_length exact values
        rl = ac.get("response_length", {})
        rl_ok = False
        if isinstance(rl, dict):
            exp = {
                "min_chars": 100,
                "max_chars": 15000,
                "ideal_min": 300,
                "ideal_max": 8000,
                "penalty_short": 2,
                "penalty_long": 1,
            }
            try:
                rl_ok = (
                    rl.get("min_chars") == exp["min_chars"]
                    and rl.get("max_chars") == exp["max_chars"]
                    and rl.get("ideal_min") == exp["ideal_min"]
                    and rl.get("ideal_max") == exp["ideal_max"]
                    and rl.get("penalty_short") == exp["penalty_short"]
                    and rl.get("penalty_long") == exp["penalty_long"]
                )
            except Exception:
                rl_ok = False
        checks["config_auto_response_length_values"] = rl_ok

        # style_consistency
        sc = ac.get("style_consistency", {})
        sc_ok = False
        if isinstance(sc, dict):
            if sc.get("max_sentence_length_std_dev") == 30:
                sc_ok = True
        checks["config_auto_style_consistency_value"] = sc_ok

    # Dimensions wired to auto checks
    wired_ok = False
    if isinstance(dims, list):
        want = {
            "tone": set(["sycophancy", "filler_words"]),
            "accuracy": set(["hedge_words"]),
            "completeness": set(["required_sections", "response_length"]),
            "format_compliance": set(["format_structure"]),
            "consistency": set(["style_consistency"]),
        }
        present = {}
        for d in dims:
            if not isinstance(d, dict):
                continue
            name = d.get("name")
            acs = d.get("auto_checks", [])
            if isinstance(name, str) and isinstance(acs, list):
                present[name] = set([str(x) for x in acs])
        try:
            conds = []
            for k, v in want.items():
                conds.append(k in present and v.issubset(present[k]))
            wired_ok = all(conds)
        except Exception:
            wired_ok = False
    checks["config_dimensions_wired_sensible"] = wired_ok

    return checks


def check_history(history_path):
    # Initialize all checks to False
    checks = {
        "history_exists": False,
        "history_two_lines": False,
        "history_lines_valid_json": False,
        "history_required_fields": False,
        "history_dimension_keys": False,
        "history_scores_in_range": False,
        "history_baseline_sycophancy_hit": False,
        "history_baseline_missing_sections_nonempty": False,
        "history_baseline_has_headers_false": False,
        "history_after_sycophancy_zero": False,
        "history_after_missing_sections_empty": False,
        "history_after_has_headers_true": False,
        "history_char_count_ints": False,
        "history_rate_numbers": False,
        "history_std_numbers": False,
        "history_after_overall_ge_baseline_plus_half": False,
        "history_after_pass_true": False,
    }

    if not os.path.isfile(history_path):
        return checks

    checks["history_exists"] = True
    objs, non_empty, err = load_json_lines(history_path)
    if objs is None:
        return checks

    # exactly two non-empty JSON lines
    if len(non_empty) == 2:
        checks["history_two_lines"] = True
    else:
        return checks  # cannot proceed further reliably

    checks["history_lines_valid_json"] = True

    # Validate each line structure
    required_dims = ["accuracy", "completeness", "tone", "format_compliance", "consistency"]
    agents = set()
    baseline_obj = None
    after_obj = None
    req_fields_ok = True
    dim_keys_ok = True
    scores_ok = True
    char_count_ints_ok = True
    rate_numbers_ok = True
    std_numbers_ok = True

    for o in objs:
        # required top-level
        if not (isinstance(o, dict) and isinstance(o.get("agent"), str) and isinstance(o.get("task_type"), str)):
            req_fields_ok = False
        else:
            agents.add(o.get("agent"))
            if o.get("agent") == "baseline":
                baseline_obj = o
            if o.get("agent") == "after":
                after_obj = o
        # overall score and pass
        if not (is_number(o.get("overall_score")) and 1 <= float(o.get("overall_score")) <= 5 and isinstance(o.get("pass"), bool)):
            scores_ok = False

        dims = o.get("dimensions")
        if not isinstance(dims, dict):
            dim_keys_ok = False
            continue
        # dimension keys
        if sorted(list(dims.keys())) != sorted(required_dims):
            dim_keys_ok = False

        # per-dimension details
        for dname in required_dims:
            ditem = dims.get(dname, {})
            if not isinstance(ditem, dict):
                dim_keys_ok = False
                continue
            if not (is_number(ditem.get("score")) and 1 <= float(ditem.get("score")) <= 5):
                scores_ok = False
            auto = ditem.get("auto", {})
            if not isinstance(auto, dict):
                req_fields_ok = False
                continue
            if dname == "accuracy":
                if not is_number(auto.get("hedge_per_1000")):
                    rate_numbers_ok = False
            elif dname == "completeness":
                if not (isinstance(auto.get("missing_sections"), list)):
                    req_fields_ok = False
                if not isinstance(auto.get("char_count"), int):
                    char_count_ints_ok = False
            elif dname == "tone":
                if not (isinstance(auto.get("sycophancy_hits"), int) and is_number(auto.get("filler_per_1000"))):
                    req_fields_ok = False
                    rate_numbers_ok = False
            elif dname == "format_compliance":
                if not isinstance(auto.get("has_headers"), bool):
                    req_fields_ok = False
            elif dname == "consistency":
                if not is_number(auto.get("sentence_length_std")):
                    std_numbers_ok = False

    checks["history_required_fields"] = req_fields_ok
    checks["history_dimension_keys"] = dim_keys_ok
    checks["history_scores_in_range"] = scores_ok
    checks["history_char_count_ints"] = char_count_ints_ok
    checks["history_rate_numbers"] = rate_numbers_ok
    checks["history_std_numbers"] = std_numbers_ok

    # Specific conditions for baseline and after
    if isinstance(baseline_obj, dict):
        b_tone = baseline_obj.get("dimensions", {}).get("tone", {}).get("auto", {})
        b_comp = baseline_obj.get("dimensions", {}).get("completeness", {}).get("auto", {})
        b_fmt = baseline_obj.get("dimensions", {}).get("format_compliance", {}).get("auto", {})
        if isinstance(b_tone.get("sycophancy_hits"), int) and b_tone.get("sycophancy_hits", 0) >= 1:
            checks["history_baseline_sycophancy_hit"] = True
        if isinstance(b_comp.get("missing_sections"), list) and len(b_comp.get("missing_sections")) >= 1:
            checks["history_baseline_missing_sections_nonempty"] = True
        if b_fmt.get("has_headers") is False:
            checks["history_baseline_has_headers_false"] = True

    if isinstance(after_obj, dict):
        a_tone = after_obj.get("dimensions", {}).get("tone", {}).get("auto", {})
        a_comp = after_obj.get("dimensions", {}).get("completeness", {}).get("auto", {})
        a_fmt = after_obj.get("dimensions", {}).get("format_compliance", {}).get("auto", {})
        if isinstance(a_tone.get("sycophancy_hits"), int) and a_tone.get("sycophancy_hits", -1) == 0:
            checks["history_after_sycophancy_zero"] = True
        if isinstance(a_comp.get("missing_sections"), list) and len(a_comp.get("missing_sections")) == 0:
            checks["history_after_missing_sections_empty"] = True
        if a_fmt.get("has_headers") is True:
            checks["history_after_has_headers_true"] = True

    # Overall improvements
    if isinstance(baseline_obj, dict) and isinstance(after_obj, dict):
        b_overall = baseline_obj.get("overall_score")
        a_overall = after_obj.get("overall_score")
        if is_number(b_overall) and is_number(a_overall):
            try:
                if float(a_overall) >= float(b_overall) + 0.5:
                    checks["history_after_overall_ge_baseline_plus_half"] = True
            except Exception:
                pass
        if isinstance(after_obj.get("pass"), bool) and after_obj.get("pass") is True:
            checks["history_after_pass_true"] = True

    return checks


def check_compare(compare_path, history_objs=None):
    checks = {
        "compare_exists": False,
        "compare_valid_json": False,
        "compare_fields_present": False,
        "compare_overall_delta_matches": False,
        "compare_dimension_deltas_positive_for_selected": False,
        "compare_overall_delta_ge_half": False,
    }

    if not os.path.isfile(compare_path):
        return checks

    checks["compare_exists"] = True
    obj, err = load_json_file(compare_path)
    if obj is None or not isinstance(obj, dict):
        return checks
    checks["compare_valid_json"] = True

    keys_ok = all(k in obj for k in ["baseline_overall", "after_overall", "overall_delta", "dimension_deltas"])
    if not keys_ok:
        return checks
    if not (
        is_number(obj["baseline_overall"])
        and is_number(obj["after_overall"])
        and is_number(obj["overall_delta"])
        and isinstance(obj["dimension_deltas"], dict)
    ):
        return checks
    req_dims = ["accuracy", "completeness", "tone", "format_compliance", "consistency"]
    if not all(d in obj["dimension_deltas"] and is_number(obj["dimension_deltas"][d]) for d in req_dims):
        return checks
    checks["compare_fields_present"] = True

    # overall delta match within tolerance 0.05
    try:
        computed = float(obj["after_overall"]) - float(obj["baseline_overall"])
        if abs(float(obj["overall_delta"]) - computed) <= 0.05:
            checks["compare_overall_delta_matches"] = True
    except Exception:
        pass

    # positive deltas for tone, completeness, format_compliance
    try:
        dd = obj["dimension_deltas"]
        if dd["tone"] > 0 and dd["completeness"] > 0 and dd["format_compliance"] > 0:
            checks["compare_dimension_deltas_positive_for_selected"] = True
    except Exception:
        pass

    # overall_delta >= 0.5
    try:
        if float(obj["overall_delta"]) >= 0.5:
            checks["compare_overall_delta_ge_half"] = True
    except Exception:
        pass

    return checks


def check_report(report_path, config_obj=None):
    checks = {
        "report_exists": False,
        "report_valid_json": False,
        "report_fields_present": False,
        "report_agent_after": False,
        "report_thresholds_correct": False,
        "report_notes_string": False,
    }

    if not os.path.isfile(report_path):
        return checks

    checks["report_exists"] = True
    obj, err = load_json_file(report_path)
    if obj is None or not isinstance(obj, dict):
        return checks
    checks["report_valid_json"] = True

    # Required fields
    fields_ok = all(k in obj for k in ["agent", "overall_score", "pass", "thresholds", "notes"])
    if not fields_ok:
        return checks
    thresholds = obj.get("thresholds", {})
    dims = thresholds.get("dimensions", {}) if isinstance(thresholds, dict) else {}
    req_dims = ["accuracy", "completeness", "tone", "format_compliance", "consistency"]
    dim_keys_ok = isinstance(dims, dict) and all(k in dims for k in req_dims)
    if not (
        isinstance(obj.get("agent"), str)
        and is_number(obj.get("overall_score"))
        and isinstance(obj.get("pass"), bool)
        and isinstance(thresholds, dict)
        and dim_keys_ok
    ):
        return checks
    checks["report_fields_present"] = True

    if obj.get("agent") == "after":
        checks["report_agent_after"] = True

    # thresholds.overall == 3.0 and thresholds.dimensions contain the five keys (numeric values)
    thr_ok = False
    try:
        overall_thr_ok = is_number(thresholds.get("overall")) and float(thresholds.get("overall")) == 3.0
        dims_vals_ok = all(is_number(dims[k]) for k in req_dims)
        if overall_thr_ok and dims_vals_ok:
            thr_ok = True
    except Exception:
        thr_ok = False
    checks["report_thresholds_correct"] = thr_ok

    # notes string non-empty
    if isinstance(obj.get("notes"), str) and obj.get("notes").strip() != "":
        checks["report_notes_string"] = True

    return checks


def check_analysis(analysis_path):
    checks = {
        "analysis_exists": False,
        "analysis_min_250_words": False,
        "analysis_contains_keywords": False,
    }

    if not os.path.isfile(analysis_path):
        return checks

    checks["analysis_exists"] = True
    try:
        txt = open(analysis_path, "r", encoding="utf-8").read()
    except Exception:
        return checks

    # Count words by whitespace
    words = [w for w in txt.split() if w.strip() != ""]
    if len(words) >= 250:
        checks["analysis_min_250_words"] = True

    lower = txt.lower()
    need = ["sycophancy", "filler", "required sections", "headers"]
    if all(n in lower for n in need):
        checks["analysis_contains_keywords"] = True

    return checks


def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    config_path = os.path.join(output_dir, "scorecard_config.json")
    history_path = os.path.join(output_dir, "history.jsonl")
    compare_path = os.path.join(output_dir, "compare.json")
    report_path = os.path.join(output_dir, "report.json")
    analysis_path = os.path.join(output_dir, "analysis.md")

    all_checks = {}

    # Config checks
    config_checks = check_config(config_path)
    all_checks.update(config_checks)

    # History checks
    history_checks = check_history(history_path)
    all_checks.update(history_checks)

    # Compare checks
    compare_checks = check_compare(compare_path)
    all_checks.update(compare_checks)

    # Report checks
    report_checks = check_report(report_path)
    all_checks.update(report_checks)

    # Analysis checks
    analysis_checks = check_analysis(analysis_path)
    all_checks.update(analysis_checks)

    # Reward calculation: fraction of passed checks; ensure 0.0 if no outputs produced (no-op baseline)
    # Artifact-dependent: require at least one of the primary deliverables to exist to avoid accidental positive reward
    primary_exists = any([
        all_checks.get("config_exists", False),
        all_checks.get("history_exists", False),
        all_checks.get("compare_exists", False),
        all_checks.get("report_exists", False),
        all_checks.get("analysis_exists", False),
    ])

    passed = sum(1 for v in all_checks.values() if v is True)
    total = len(all_checks)
    reward = 0.0
    if primary_exists and total > 0:
        reward = passed / total
        # Clamp to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0
    else:
        reward = 0.0

    result = {"reward": reward}
    # Append all boolean checks
    for k, v in all_checks.items():
        result[k] = bool(v)

    print(json.dumps(result))


if __name__ == "__main__":
    main()