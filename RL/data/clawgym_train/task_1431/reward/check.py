import json
import os
import sys
import csv
import re

# Try to import PyYAML; fall back to JSON parsing if not available (limited)
try:
    import yaml  # type: ignore
except Exception:
    yaml = None

def load_yaml(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        if yaml is not None:
            return yaml.safe_load(text)
        # Fallback: attempt JSON if YAML module unavailable
        text_stripped = text.strip()
        if text_stripped.startswith("{") or text_stripped.startswith("["):
            return json.loads(text_stripped)
        return None
    except Exception:
        return None

def is_number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
            return True
        except Exception:
            return False
    return False

def to_float(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return None
    return None

def has_key(d, key):
    return isinstance(d, dict) and key in d

def get_word_count(text):
    return len(re.findall(r"\b\w+\b", text))

def read_csv_row_count(csv_path):
    # Count data rows excluding header and empty lines
    if not os.path.isfile(csv_path):
        return None
    count = 0
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return 0
        # Assume first non-empty row is header
        data_rows = rows[1:] if len(rows) > 1 else []
        for row in data_rows:
            # consider row empty if all cells empty after strip
            if any((cell or "").strip() for cell in row):
                count += 1
        return count
    except Exception:
        return None

def ensure_list(obj):
    return isinstance(obj, list)

def ensure_dict(obj):
    return isinstance(obj, dict)

def string_contains_timeframe(s):
    if not isinstance(s, str):
        return False
    s_lower = s.lower()
    timeframe_tokens = ["day", "days", "week", "weeks", "month", "months", "quarter", "quarters", "year", "years", "q1", "q2", "q3", "q4"]
    has_digit = any(ch.isdigit() for ch in s)
    has_time = any(tok in s_lower for tok in timeframe_tokens)
    return has_digit and has_time

def non_increasing(seq, eps=1e-9):
    for i in range(1, len(seq)):
        if seq[i] - seq[i-1] > eps:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False)
    checks = {
        # Strategy
        "strategy_exists": False,
        "strategy_yaml_valid": False,
        "strategy_required_keys": False,
        "strategy_antigoals_len": False,
        "strategy_key_assumptions_len3": False,
        "strategy_key_assumptions_fields": False,
        "strategy_comp_landscape_keys": False,
        # Prioritization
        "prioritization_exists": False,
        "prioritization_yaml_valid": False,
        "prioritization_has_features_list": False,
        "prioritization_count_matches_input": False,
        "prioritization_each_feature_required_fields": False,
        "prioritization_sorted_by_score": False,
        # Roadmap
        "roadmap_exists": False,
        "roadmap_yaml_valid": False,
        "roadmap_has_now_next_later_items_counts": False,
        "roadmap_items_fields_present": False,
        # Spec for top initiative
        "spec_exists": False,
        "spec_yaml_valid": False,
        "spec_title_matches_top_feature": False,
        "spec_problem_fields": False,
        "spec_solution_out_of_scope_present": False,
        "spec_success_primary_format": False,
        "spec_risks_count_and_fields": False,
        "spec_timeline_fields": False,
        "spec_spec_quality_score_range": False,
        # Metrics / North Star
        "metrics_exists": False,
        "metrics_yaml_valid": False,
        "metrics_required_fields": False,
        "metrics_leading_indicators_count_and_fields": False,
        "metrics_guardrails_fields": False,
        "metrics_input_metrics_fields": False,
        # Stakeholders
        "stakeholders_exists": False,
        "stakeholders_yaml_valid": False,
        "stakeholders_list_and_len": False,
        "stakeholders_each_fields_present": False,
        # README
        "readme_exists": False,
        "readme_word_count_leq_300": False,
    }

    # Paths
    strategy_path = os.path.join(output_dir, "product", "strategy.yaml")
    prioritization_path = os.path.join(output_dir, "product", "prioritization.yaml")
    roadmap_path = os.path.join(output_dir, "product", "roadmap.yaml")
    spec_path = os.path.join(output_dir, "product", "specs", "one-pagers", "top-initiative.yaml")
    metrics_path = os.path.join(output_dir, "product", "metrics", "north-star.yaml")
    stakeholders_path = os.path.join(output_dir, "product", "stakeholders", "map.yaml")
    readme_path = os.path.join(output_dir, "product", "README.md")

    feature_csv_path = os.path.join(input_dir, "feature_ideas.csv")

    # 1) Strategy
    strategy_data = None
    if os.path.isfile(strategy_path):
        checks["strategy_exists"] = True
        strategy_data = load_yaml(strategy_path)
        if strategy_data is not None:
            checks["strategy_yaml_valid"] = True
            if isinstance(strategy_data, dict) and "product_strategy" in strategy_data and isinstance(strategy_data["product_strategy"], dict):
                ps = strategy_data["product_strategy"]
                required_keys = [
                    "vision", "mission", "target_customer", "problem", "business_model",
                    "success_metric", "moat_type", "anti_goals", "key_assumptions",
                    "competitive_landscape"
                ]
                if all(k in ps for k in required_keys):
                    checks["strategy_required_keys"] = True
                # anti_goals list length >=2
                if "anti_goals" in ps and isinstance(ps["anti_goals"], list) and len(ps["anti_goals"]) >= 2:
                    checks["strategy_antigoals_len"] = True
                # key_assumptions list length >=3 and each has fields
                if "key_assumptions" in ps and isinstance(ps["key_assumptions"], list) and len(ps["key_assumptions"]) >= 3:
                    checks["strategy_key_assumptions_len3"] = True
                    all_fields = True
                    for item in ps["key_assumptions"]:
                        if not isinstance(item, dict):
                            all_fields = False
                            break
                        if not all(field in item for field in ["assumption", "validation_method", "status"]):
                            all_fields = False
                            break
                    if all_fields:
                        checks["strategy_key_assumptions_fields"] = True
                # competitive_landscape keys
                cl_ok = False
                if "competitive_landscape" in ps and isinstance(ps["competitive_landscape"], dict):
                    cl = ps["competitive_landscape"]
                    direct_ok = "direct" in cl and isinstance(cl["direct"], list)
                    indirect_ok = "indirect" in cl and isinstance(cl["indirect"], list)
                    do_nothing_ok = "do_nothing" in cl and isinstance(cl["do_nothing"], str)
                    cl_ok = direct_ok and indirect_ok and do_nothing_ok
                if cl_ok:
                    checks["strategy_comp_landscape_keys"] = True

    # 2) Prioritization
    prioritization_data = None
    top_feature_name = None
    if os.path.isfile(prioritization_path):
        checks["prioritization_exists"] = True
        prioritization_data = load_yaml(prioritization_path)
        if prioritization_data is not None:
            checks["prioritization_yaml_valid"] = True
            # Expect top-level 'features' list
            features = None
            if isinstance(prioritization_data, dict) and "features" in prioritization_data:
                features = prioritization_data["features"]
                if isinstance(features, list):
                    checks["prioritization_has_features_list"] = True
                    # Count check vs input CSV
                    expected_count = read_csv_row_count(feature_csv_path)
                    if expected_count is not None and len(features) == expected_count:
                        checks["prioritization_count_matches_input"] = True
                    # Each feature required fields
                    all_ok = True
                    rice_scores = []
                    for feat in features:
                        if not isinstance(feat, dict):
                            all_ok = False
                            break
                        name_ok = "name" in feat
                        reach_ok = "reach" in feat and isinstance(feat["reach"], dict) and \
                                   "users_affected" in feat["reach"] and is_number(feat["reach"]["users_affected"]) and \
                                   "segment" in feat["reach"]
                        impact_ok = "impact" in feat and isinstance(feat["impact"], dict) and \
                                    "on_north_star" in feat["impact"] and \
                                    "magnitude" in feat["impact"] and is_number(feat["impact"]["magnitude"]) and \
                                    "confidence" in feat["impact"] and is_number(feat["impact"]["confidence"])
                        # confidence between 0 and 1
                        if impact_ok:
                            conf_v = to_float(feat["impact"]["confidence"])
                            if conf_v is None or not (0.0 <= conf_v <= 1.0):
                                impact_ok = False
                        effort_ok = "effort" in feat and isinstance(feat["effort"], dict) and \
                                    "eng_weeks" in feat["effort"] and is_number(feat["effort"]["eng_weeks"]) and \
                                    "design_weeks" in feat["effort"] and is_number(feat["effort"]["design_weeks"]) and \
                                    "score" in feat["effort"] and is_number(feat["effort"]["score"])
                        # effort.score in 1..10
                        if effort_ok:
                            sc = to_float(feat["effort"]["score"])
                            if sc is None or sc < 1 or sc > 10:
                                effort_ok = False
                        strat_ok = "strategic_fit" in feat and isinstance(feat["strategic_fit"], dict) and \
                                   "score" in feat["strategic_fit"] and is_number(feat["strategic_fit"]["score"])
                        # strategic_fit.score in 1..5
                        if strat_ok:
                            sfs = to_float(feat["strategic_fit"]["score"])
                            if sfs is None or sfs < 1 or sfs > 5:
                                strat_ok = False
                        rice_ok = "rice_plus_score" in feat and is_number(feat["rice_plus_score"])
                        if not (name_ok and reach_ok and impact_ok and effort_ok and strat_ok and rice_ok):
                            all_ok = False
                            break
                        rice_scores.append(to_float(feat["rice_plus_score"]))
                    if all_ok:
                        checks["prioritization_each_feature_required_fields"] = True
                        # Sorted by rice_plus_score descending
                        if rice_scores and non_increasing(rice_scores):
                            checks["prioritization_sorted_by_score"] = True
                        # Top feature name
                        if isinstance(features[0], dict) and "name" in features[0]:
                            top_feature_name = features[0]["name"]

    # 3) Roadmap
    roadmap_data = None
    if os.path.isfile(roadmap_path):
        checks["roadmap_exists"] = True
        roadmap_data = load_yaml(roadmap_path)
        if roadmap_data is not None:
            checks["roadmap_yaml_valid"] = True
            rm = roadmap_data.get("roadmap") if isinstance(roadmap_data, dict) else None
            counts_ok = False
            items_fields_ok = False
            if isinstance(rm, dict):
                now_items = (((rm.get("now") or {}).get("items")) if isinstance(rm.get("now"), dict) else None)
                next_items = (((rm.get("next") or {}).get("items")) if isinstance(rm.get("next"), dict) else None)
                later_items = (((rm.get("later") or {}).get("items")) if isinstance(rm.get("later"), dict) else None)
                if isinstance(now_items, list) and len(now_items) >= 2 and \
                   isinstance(next_items, list) and len(next_items) >= 2 and \
                   isinstance(later_items, list) and len(later_items) >= 2:
                    counts_ok = True
                    # Check each item has name, outcome, status, confidence
                    def items_have_fields(items):
                        for it in items:
                            if not isinstance(it, dict):
                                return False
                            if not all(k in it for k in ["name", "outcome", "status", "confidence"]):
                                return False
                        return True
                    if items_have_fields(now_items) and items_have_fields(next_items) and items_have_fields(later_items):
                        items_fields_ok = True
            if counts_ok:
                checks["roadmap_has_now_next_later_items_counts"] = True
            if items_fields_ok:
                checks["roadmap_items_fields_present"] = True

    # 4) Spec (top initiative)
    spec_data = None
    if os.path.isfile(spec_path):
        checks["spec_exists"] = True
        spec_data = load_yaml(spec_path)
        if spec_data is not None:
            checks["spec_yaml_valid"] = True
            op = spec_data.get("one_pager") if isinstance(spec_data, dict) else None
            if isinstance(op, dict):
                # Title matches top feature
                if top_feature_name is not None and isinstance(op.get("title"), str) and op.get("title") == top_feature_name:
                    checks["spec_title_matches_top_feature"] = True
                # Problem fields
                prob = op.get("problem")
                if isinstance(prob, dict) and isinstance(prob.get("statement"), str) and isinstance(prob.get("evidence"), (str, list, dict)):
                    checks["spec_problem_fields"] = True
                # Solution out_of_scope list length >=1
                sol = op.get("solution")
                if isinstance(sol, dict) and isinstance(sol.get("out_of_scope"), list) and len(sol.get("out_of_scope")) >= 1:
                    checks["spec_solution_out_of_scope_present"] = True
                # Success metrics primary string with metric+target+timeframe (heuristic)
                sm = op.get("success_metrics")
                primary_ok = False
                if isinstance(sm, dict) and isinstance(sm.get("primary"), str) and string_contains_timeframe(sm.get("primary")):
                    primary_ok = True
                if primary_ok:
                    checks["spec_success_primary_format"] = True
                # Risks list >=2 with likelihood and mitigation
                risks = op.get("risks")
                risks_ok = False
                if isinstance(risks, list) and len(risks) >= 2:
                    risks_ok = True
                    for r in risks:
                        if not (isinstance(r, dict) and "likelihood" in r and "mitigation" in r):
                            risks_ok = False
                            break
                if risks_ok:
                    checks["spec_risks_count_and_fields"] = True
                # Timeline fields
                tl = op.get("timeline")
                if isinstance(tl, dict) and "target_ship" in tl and isinstance(tl.get("milestones"), list) and len(tl.get("milestones")) >= 2:
                    checks["spec_timeline_fields"] = True
                # Spec quality score range
                sqs = spec_data.get("spec_quality_score") if "spec_quality_score" in spec_data else op.get("spec_quality_score") if isinstance(op, dict) else None
                # spec_quality_score is top-level per task; accept either top-level or nested for flexibility
                if is_number(sqs):
                    val = to_float(sqs)
                    if val is not None and 14 <= val <= 20 and float(val).is_integer():
                        checks["spec_spec_quality_score_range"] = True

    # 5) Metrics North Star
    metrics_data = None
    if os.path.isfile(metrics_path):
        checks["metrics_exists"] = True
        metrics_data = load_yaml(metrics_path)
        if metrics_data is not None:
            checks["metrics_yaml_valid"] = True
            metrics_root = metrics_data.get("metrics") if isinstance(metrics_data, dict) else None
            if isinstance(metrics_root, dict):
                ns = metrics_root.get("north_star")
                leading = metrics_root.get("leading_indicators")
                guards = metrics_root.get("guardrails")
                input_metrics = metrics_root.get("input_metrics")
                # Required fields
                if isinstance(ns, dict) and "metric" in ns and "target" in ns:
                    checks["metrics_required_fields"] = True
                # Leading indicators count and fields
                li_ok = False
                if isinstance(leading, list) and len(leading) >= 2:
                    li_ok = True
                    for li in leading:
                        if not (isinstance(li, dict) and all(k in li for k in ["name", "target", "owner", "update_frequency"])):
                            li_ok = False
                            break
                if li_ok:
                    checks["metrics_leading_indicators_count_and_fields"] = True
                # Guardrails
                gr_ok = False
                if isinstance(guards, list) and len(guards) >= 1:
                    gr_ok = True
                    for g in guards:
                        if not (isinstance(g, dict) and "name" in g and "threshold" in g):
                            gr_ok = False
                            break
                if gr_ok:
                    checks["metrics_guardrails_fields"] = True
                # Input metrics
                im_ok = False
                if isinstance(input_metrics, dict) and all(k in input_metrics for k in ["breadth", "depth", "frequency", "efficiency"]):
                    im_ok = True
                if im_ok:
                    checks["metrics_input_metrics_fields"] = True

    # 6) Stakeholders
    stakeholders_data = None
    if os.path.isfile(stakeholders_path):
        checks["stakeholders_exists"] = True
        stakeholders_data = load_yaml(stakeholders_path)
        if stakeholders_data is not None:
            checks["stakeholders_yaml_valid"] = True
            if isinstance(stakeholders_data, dict) and "stakeholders" in stakeholders_data and isinstance(stakeholders_data["stakeholders"], list):
                s_list = stakeholders_data["stakeholders"]
                if len(s_list) >= 4:
                    checks["stakeholders_list_and_len"] = True
                    all_ok = True
                    for s in s_list:
                        if not isinstance(s, dict):
                            all_ok = False
                            break
                        if not all(k in s for k in ["name", "role", "influence", "interest", "strategy", "communication", "concerns", "wins"]):
                            all_ok = False
                            break
                        comm = s.get("communication")
                        if not (isinstance(comm, dict) and "frequency" in comm and "format" in comm):
                            all_ok = False
                            break
                        if not (isinstance(s.get("concerns"), list) and isinstance(s.get("wins"), list)):
                            all_ok = False
                            break
                    if all_ok:
                        checks["stakeholders_each_fields_present"] = True

    # 7) README
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_text = f.read()
            if get_word_count(readme_text) <= 300:
                checks["readme_word_count_leq_300"] = True
        except Exception:
            pass

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # No-op baseline: if output dir missing or no required artifacts exist, reward must be 0.0
    required_files = [strategy_path, prioritization_path, roadmap_path, spec_path, metrics_path, stakeholders_path, readme_path]
    any_required_exists = any(os.path.isfile(p) for p in required_files)
    if not any_required_exists:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Clamp reward to [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()