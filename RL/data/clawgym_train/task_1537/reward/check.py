import json
import os
import sys
import re

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def load_yaml_file(path):
    # Returns (data, ok)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None, False
    # Try PyYAML first
    try:
        import yaml  # type: ignore
        try:
            data = yaml.safe_load(content)
            return data, True
        except Exception:
            return None, False
    except Exception:
        # Fallback: try JSON (YAML is a superset; valid JSON will parse)
        try:
            data = json.loads(content)
            return data, True
        except Exception:
            return None, False

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def check_program_yaml(prog):
    checks = {
        "program_has_required_keys": False,
        "program_sessions_per_week_is_5": False,
        "program_movement_patterns_exact_8": False,
        "program_cardio_80_20": False,
        "program_weeks_structure_valid": False,
        "program_has_deload_week": False,
        "program_sessions_structure_valid": False,
    }

    if not isinstance(prog, dict):
        return checks

    required_top = ["program","target_event","training_age_level","sessions_per_week","movement_patterns_covered","cardio_plan","weeks","sessions","progression_rules","taper"]
    has_all = all(k in prog for k in required_top)
    # program.level and frequency non-empty strings
    sub_ok = False
    if has_all and isinstance(prog.get("program"), dict):
        lvl = prog["program"].get("level")
        freq = prog["program"].get("frequency")
        sub_ok = isinstance(lvl, str) and lvl.strip() != "" and isinstance(freq, str) and freq.strip() != ""
    checks["program_has_required_keys"] = has_all and sub_ok

    # sessions_per_week equals 5 (integer)
    spw = prog.get("sessions_per_week")
    checks["program_sessions_per_week_is_5"] = isinstance(spw, int) and spw == 5

    # movement patterns exact 8
    patterns_required = ["Horizontal Push","Horizontal Pull","Vertical Push","Vertical Pull","Squat","Hinge","Carry/Core","Lunge/Single-leg"]
    mp = prog.get("movement_patterns_covered")
    if isinstance(mp, list) and len(mp) == 8:
        try:
            checks["program_movement_patterns_exact_8"] = set(mp) == set(patterns_required)
        except Exception:
            checks["program_movement_patterns_exact_8"] = False

    # cardio 80/20
    cardio = prog.get("cardio_plan")
    ok_cardio = False
    if isinstance(cardio, dict):
        wd = cardio.get("weekly_distribution")
        if isinstance(wd, dict):
            z12 = wd.get("zone1_2_pct")
            z35 = wd.get("zone3_5_pct")
            if is_number(z12) and is_number(z35):
                ok_cardio = (z12 >= 80) and (z35 <= 20)
    checks["program_cardio_80_20"] = ok_cardio

    # weeks structure
    weeks = prog.get("weeks")
    weeks_ok = False
    deload_true = False
    if isinstance(weeks, dict):
        expected_keys = [str(i) for i in range(1, 13)]
        if set(weeks.keys()) == set(expected_keys):
            all_ok = True
            for k in expected_keys:
                w = weeks.get(k)
                if not isinstance(w, dict):
                    all_ok = False
                    break
                intensity = w.get("intensity_rpe")
                vol = w.get("volume_modifier")
                deload = w.get("deload")
                # intensity string, volume number, deload boolean
                if not (isinstance(intensity, str) and intensity.strip() != ""):
                    all_ok = False
                    break
                if not is_number(vol):
                    all_ok = False
                    break
                if not isinstance(deload, bool):
                    all_ok = False
                    break
                if deload:
                    deload_true = True
            weeks_ok = all_ok
    checks["program_weeks_structure_valid"] = weeks_ok
    checks["program_has_deload_week"] = deload_true

    # sessions structure
    sess = prog.get("sessions")
    sessions_ok = False
    if isinstance(sess, dict):
        day_keys = [f"day_{i}" for i in range(1, 6)]
        if all(k in sess for k in day_keys):
            all_days_ok = True
            for dk in day_keys:
                day = sess.get(dk)
                if not isinstance(day, dict):
                    all_days_ok = False
                    break
                name = day.get("name")
                exs = day.get("exercises")
                if not (isinstance(name, str) and name.strip() != ""):
                    all_days_ok = False
                    break
                if not (isinstance(exs, list) and len(exs) > 0):
                    all_days_ok = False
                    break
                for ex in exs:
                    if not isinstance(ex, dict):
                        all_days_ok = False
                        break
                    # required: name, sets, reps, progression
                    if not (isinstance(ex.get("name"), str) and ex.get("name").strip() != ""):
                        all_days_ok = False
                        break
                    if not is_number(ex.get("sets")):
                        all_days_ok = False
                        break
                    if not (isinstance(ex.get("reps"), str) and ex.get("reps").strip() != ""):
                        all_days_ok = False
                        break
                    if "progression" not in ex or not isinstance(ex.get("progression"), str):
                        all_days_ok = False
                        break
                    # at least one of rpe or tempo present
                    has_rpe = "rpe" in ex
                    has_tempo = "tempo" in ex
                    if not (has_rpe or has_tempo):
                        all_days_ok = False
                        break
                if not all_days_ok:
                    break
            sessions_ok = all_days_ok
    checks["program_sessions_structure_valid"] = sessions_ok

    return checks

def check_nutrition_yaml(nut):
    checks = {
        "nutrition_has_required_keys": False,
        "nutrition_macros_per_kg_in_range": False,
    }
    if not isinstance(nut, dict):
        return checks

    # required keys presence and numeric types
    bw = nut.get("body_weight_kg")
    goal = nut.get("goal")
    daily = nut.get("daily_targets")
    mpk = nut.get("macros_per_kg")
    rationale = nut.get("rationale")

    key_ok = (
        is_number(bw) and
        isinstance(goal, str) and goal.strip() != "" and
        isinstance(daily, dict) and
        is_number(daily.get("calories_kcal")) and
        is_number(daily.get("protein_g")) and
        is_number(daily.get("carbs_g")) and
        is_number(daily.get("fat_g")) and
        isinstance(mpk, dict) and
        is_number(mpk.get("protein_g_per_kg")) and
        is_number(mpk.get("carbs_g_per_kg")) and
        is_number(mpk.get("fat_g_per_kg")) and
        isinstance(rationale, str)
    )
    checks["nutrition_has_required_keys"] = key_ok

    in_range = False
    if isinstance(mpk, dict):
        p = mpk.get("protein_g_per_kg")
        c = mpk.get("carbs_g_per_kg")
        if is_number(p) and is_number(c):
            in_range = (1.8 <= p <= 2.4) and (4.0 <= c <= 6.0)
    checks["nutrition_macros_per_kg_in_range"] = in_range

    return checks

def check_tracker_yaml(trk):
    checks = {
        "tracker_has_required_keys": False,
        "tracker_workout_template_fields_present": False,
        "tracker_weekly_review_template_fields_present": False,
    }
    if not isinstance(trk, dict):
        return checks

    has_keys = "workout_log_template" in trk and "weekly_review_template" in trk
    checks["tracker_has_required_keys"] = has_keys

    wlt_fields = ["date","day","duration_min","readiness_score","exercises","cardio","session_notes","next_session_adjustments"]
    wrt_fields = ["week_of","sessions_completed","sessions_planned","strength_progress","body_composition","cardio_volume","recovery_metrics","wins","challenges","adjustments_for_next_week"]

    wlt_ok = False
    wlt = trk.get("workout_log_template")
    if isinstance(wlt, dict):
        wlt_ok = all(k in wlt for k in wlt_fields)
    checks["tracker_workout_template_fields_present"] = wlt_ok

    wrt_ok = False
    wrt = trk.get("weekly_review_template")
    if isinstance(wrt, dict):
        wrt_ok = all(k in wrt for k in wrt_fields)
    checks["tracker_weekly_review_template_fields_present"] = wrt_ok

    return checks

def check_health_md(text):
    checks = {
        "health_is_non_empty_text": False,
        "health_has_total_score_line": False,
        "health_mentions_required_signals": False,
        "health_has_recommendation_or_fix": False,
    }
    if isinstance(text, str) and text.strip() != "":
        checks["health_is_non_empty_text"] = True
        # Total Score: X/16 on same line
        lines = text.splitlines()
        has_score = False
        for ln in lines:
            if "Total Score:" in ln and "/16" in ln:
                # Optional stricter regex
                if re.search(r"Total Score:\s*\d+\s*/16", ln):
                    has_score = True
                    break
        checks["health_has_total_score_line"] = has_score

        # Mentions at least three signals
        signals = [
            "Progressive overload",
            "Program structure",
            "Recovery management",
            "Nutrition alignment",
            "Movement quality",
            "Balance",
            "Consistency",
            "Goal specificity",
        ]
        txt_lower = text.lower()
        count = 0
        for s in signals:
            if s.lower() in txt_lower:
                count += 1
        checks["health_mentions_required_signals"] = (count >= 3)

        # Contains recommendation or fix (case-insensitive)
        if re.search(r"\b(recommendation|recommendations|fix|fixes)\b", txt_lower):
            checks["health_has_recommendation_or_fix"] = True

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Existence and parseability
        "program_exists": False,
        "program_yaml_parsed": False,

        "nutrition_exists": False,
        "nutrition_yaml_parsed": False,

        "tracker_exists": False,
        "tracker_yaml_parsed": False,

        "health_exists": False,
    }

    # Paths
    program_path = os.path.join(output_dir, "program.yaml")
    nutrition_path = os.path.join(output_dir, "nutrition.yaml")
    tracker_path = os.path.join(output_dir, "tracker_templates.yaml")
    health_path = os.path.join(output_dir, "health_check.md")

    # Program checks
    prog_data = None
    if os.path.isfile(program_path):
        checks["program_exists"] = True
        prog_data, ok = load_yaml_file(program_path)
        checks["program_yaml_parsed"] = ok
        if ok:
            program_checks = check_program_yaml(prog_data)
            checks.update(program_checks)
        else:
            # Initialize program-dependent checks to False if not parsed
            checks.update({
                "program_has_required_keys": False,
                "program_sessions_per_week_is_5": False,
                "program_movement_patterns_exact_8": False,
                "program_cardio_80_20": False,
                "program_weeks_structure_valid": False,
                "program_has_deload_week": False,
                "program_sessions_structure_valid": False,
            })
    else:
        # Ensure all program-dependent checks are present and False
        checks.update({
            "program_has_required_keys": False,
            "program_sessions_per_week_is_5": False,
            "program_movement_patterns_exact_8": False,
            "program_cardio_80_20": False,
            "program_weeks_structure_valid": False,
            "program_has_deload_week": False,
            "program_sessions_structure_valid": False,
        })

    # Nutrition checks
    nut_data = None
    if os.path.isfile(nutrition_path):
        checks["nutrition_exists"] = True
        nut_data, ok = load_yaml_file(nutrition_path)
        checks["nutrition_yaml_parsed"] = ok
        if ok:
            nutrition_checks = check_nutrition_yaml(nut_data)
            checks.update(nutrition_checks)
        else:
            checks.update({
                "nutrition_has_required_keys": False,
                "nutrition_macros_per_kg_in_range": False,
            })
    else:
        checks.update({
            "nutrition_has_required_keys": False,
            "nutrition_macros_per_kg_in_range": False,
        })

    # Tracker checks
    trk_data = None
    if os.path.isfile(tracker_path):
        checks["tracker_exists"] = True
        trk_data, ok = load_yaml_file(tracker_path)
        checks["tracker_yaml_parsed"] = ok
        if ok:
            tracker_checks = check_tracker_yaml(trk_data)
            checks.update(tracker_checks)
        else:
            checks.update({
                "tracker_has_required_keys": False,
                "tracker_workout_template_fields_present": False,
                "tracker_weekly_review_template_fields_present": False,
            })
    else:
        checks.update({
            "tracker_has_required_keys": False,
            "tracker_workout_template_fields_present": False,
            "tracker_weekly_review_template_fields_present": False,
        })

    # Health check markdown
    if os.path.isfile(health_path):
        checks["health_exists"] = True
        txt = read_text_file(health_path)
        health_checks = check_health_md(txt if txt is not None else "")
        checks.update(health_checks)
    else:
        checks.update({
            "health_is_non_empty_text": False,
            "health_has_total_score_line": False,
            "health_mentions_required_signals": False,
            "health_has_recommendation_or_fix": False,
        })

    # Compute reward as fraction of passed checks
    # All checks are boolean except the existence and parsed; we included those too
    bool_values = [v for v in checks.values() if isinstance(v, bool)]
    passed = sum(1 for v in bool_values if v)
    total = len(bool_values)
    reward = 0.0
    if total > 0:
        reward = passed / total
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()