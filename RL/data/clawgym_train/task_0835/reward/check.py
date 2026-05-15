import json
import os
import sys
import re
from typing import Any

def read_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)

def float_equals(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> bool:
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

def str_contains_number(text: str, value: float) -> bool:
    # Try several common string representations for matching within text
    candidates = set()
    candidates.add(str(value))
    # Add formatted with 1-4 decimals, strip trailing zeros/decimal
    for d in range(1, 5):
        s = f"{value:.{d}f}"
        candidates.add(s)
        candidates.add(s.rstrip('0').rstrip('.') if '.' in s else s)
    # Add integer form if close to integer
    if float_equals(value, round(value)):
        candidates.add(str(int(round(value))))
    # Search for any candidate as a standalone number (allow within text as substring)
    for cand in sorted(candidates, key=len, reverse=True):
        if cand and cand in text:
            return True
    return False

def extract_section(text: str, header: str):
    # Returns content of a section starting at a header line until the next "## " (or end)
    start_idx = text.find(header)
    if start_idx == -1:
        return ""
    # Start after the header line
    next_header_match = re.search(r"\n##\s+", text[start_idx + 1:])
    if next_header_match:
        end_idx = start_idx + 1 + next_header_match.start()
        return text[start_idx:end_idx]
    return text[start_idx:]

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    pred_path = os.path.join(output_dir, "predictions.json")
    cap_path = os.path.join(output_dir, "capacity.json")
    plan_path = os.path.join(output_dir, "plan.md")
    config_path = os.path.join(input_dir, "config.json")

    # Initialize required file presence checks
    checks["predictions_exists"] = os.path.isfile(pred_path)
    checks["capacity_exists"] = os.path.isfile(cap_path)
    checks["plan_exists"] = os.path.isfile(plan_path)

    # Read config for validation parameters
    config, config_err = read_json_file(config_path)
    # If config is missing or invalid, we cannot validate lengths and matching fields deterministically.
    # However, the task requires input files, so assume config must exist; if not, later checks won't pass.
    horizon = None
    min_data_points_req = 5
    scale_up_thr = None
    scale_down_thr = None
    current_instances = None
    target_utilization = None
    if isinstance(config, dict):
        horizon = config.get("horizon", None)
        if isinstance(horizon, float) and horizon.is_integer():
            horizon = int(horizon)
        if not isinstance(horizon, int):
            # Try to coerce if it's numeric
            if is_number(horizon):
                horizon = int(round(float(horizon)))
            else:
                horizon = None
        mdp = config.get("minDataPoints")
        if is_number(mdp):
            min_data_points_req = int(round(float(mdp)))
            if min_data_points_req < 1:
                min_data_points_req = 5
        su = config.get("scaleUpThreshold")
        sd = config.get("scaleDownThreshold")
        if is_number(su):
            scale_up_thr = float(su)
        if is_number(sd):
            scale_down_thr = float(sd)
        current_instances_cfg = config.get("current_instances")
        target_util_cfg = config.get("target_utilization")
        if is_int(current_instances_cfg):
            current_instances = current_instances_cfg
        elif is_number(current_instances_cfg):
            current_instances = int(round(float(current_instances_cfg)))
        if is_number(target_util_cfg):
            target_utilization = float(target_util_cfg)

    # Parse predictions.json
    predictions = None
    if checks["predictions_exists"]:
        predictions, pred_err = read_json_file(pred_path)
        checks["predictions_json_valid"] = isinstance(predictions, dict)
    else:
        checks["predictions_json_valid"] = False

    # Parse capacity.json
    capacity = None
    if checks["capacity_exists"]:
        capacity, cap_err = read_json_file(cap_path)
        checks["capacity_json_valid"] = isinstance(capacity, dict)
    else:
        checks["capacity_json_valid"] = False

    # Read plan.md
    plan_text = ""
    if checks["plan_exists"]:
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_text = f.read()
        except Exception:
            plan_text = ""

    # Early gating: if any required output missing or invalid JSON for required JSON files, reward will be 0.0
    # but we still continue to set booleans for transparency.
    # Validate predictions.json structure
    checks["predictions_has_keys"] = False
    checks["predictions_resources_complete"] = False
    checks["combined_recommendation_valid"] = False

    allowed_actions = {"scale_up", "scale_down", "maintain", "unknown"}
    allowed_trends = {"increasing", "decreasing", "stable", "volatile"}

    resources = ["cpu", "memory", "requests"]

    # Initialize per-resource checks to False
    for r in resources:
        checks[f"{r}_pred_length_correct"] = False
        checks[f"{r}_confidence_valid"] = False
        checks[f"{r}_trend_valid"] = False
        checks[f"{r}_bursty_valid"] = False
        checks[f"{r}_recommendation_valid"] = False
        checks[f"{r}_statistics_valid"] = False
        checks[f"{r}_stats_min_points_ok"] = False

    if isinstance(predictions, dict):
        has_resources = isinstance(predictions.get("resources"), dict)
        has_combined = isinstance(predictions.get("combinedRecommendation"), dict)
        checks["predictions_has_keys"] = has_resources and has_combined
        if has_resources:
            res_obj = predictions["resources"]
            checks["predictions_resources_complete"] = all(k in res_obj for k in resources)

            # Validate combined recommendation action
            if has_combined:
                cra = predictions.get("combinedRecommendation", {}).get("action")
                checks["combined_recommendation_valid"] = isinstance(cra, str) and cra in allowed_actions

            # Per-resource validations
            for r in resources:
                r_ok = isinstance(res_obj.get(r), dict)
                if not r_ok:
                    continue
                r_obj = res_obj[r]

                # predictions length equals horizon
                preds = r_obj.get("predictions")
                if isinstance(preds, list) and horizon is not None:
                    checks[f"{r}_pred_length_correct"] = len(preds) == int(horizon)

                # confidence numeric in [0,1]
                conf = r_obj.get("confidence")
                if is_number(conf):
                    checks[f"{r}_confidence_valid"] = 0.0 <= float(conf) <= 1.0

                # trend allowed
                trend = r_obj.get("trend")
                if isinstance(trend, str):
                    checks[f"{r}_trend_valid"] = trend in allowed_trends

                # bursty object
                bursty = r_obj.get("bursty")
                burst_ok = False
                if isinstance(bursty, dict):
                    is_b = bursty.get("isBursty")
                    bf = bursty.get("burstFactor")
                    if isinstance(is_b, bool) and is_number(bf):
                        burst_ok = True
                checks[f"{r}_bursty_valid"] = burst_ok

                # recommendation action allowed
                rec = r_obj.get("recommendation")
                rec_ok = False
                if isinstance(rec, dict):
                    act = rec.get("action")
                    if isinstance(act, str) and act in allowed_actions:
                        rec_ok = True
                checks[f"{r}_recommendation_valid"] = rec_ok

                # statistics
                stats = r_obj.get("statistics")
                stats_ok = False
                stats_mindp_ok = False
                if isinstance(stats, dict):
                    mean = stats.get("mean")
                    stddev = stats.get("stdDev")
                    minv = stats.get("min")
                    maxv = stats.get("max")
                    dps = stats.get("dataPoints")
                    numeric_ok = all(is_number(v) for v in [mean, stddev, minv, maxv])
                    dps_ok = is_int(dps)
                    stats_ok = numeric_ok and dps_ok
                    if dps_ok:
                        req = min_data_points_req if isinstance(min_data_points_req, int) else 5
                        stats_mindp_ok = dps >= req
                checks[f"{r}_statistics_valid"] = stats_ok
                checks[f"{r}_stats_min_points_ok"] = stats_mindp_ok

    # Capacity validations
    checks["capacity_has_required_fields"] = False
    checks["capacity_basis_cpu"] = False
    checks["capacity_matches_config"] = False
    checks["capacity_target_util_range"] = False
    checks["capacity_needed_instances_valid"] = False
    checks["capacity_action_valid"] = False

    if isinstance(capacity, dict):
        required_fields = [
            "basis",
            "current_instances",
            "target_utilization",
            "predicted_peak",
            "needed_instances",
            "changePercent",
            "action",
        ]
        has_all = all(k in capacity for k in required_fields)
        types_ok = (
            isinstance(capacity.get("basis"), str)
            and is_int(capacity.get("current_instances"))
            and is_number(capacity.get("target_utilization"))
            and is_number(capacity.get("predicted_peak"))
            and is_int(capacity.get("needed_instances"))
            and is_number(capacity.get("changePercent"))
            and isinstance(capacity.get("action"), str)
        )
        checks["capacity_has_required_fields"] = has_all and types_ok
        checks["capacity_basis_cpu"] = capacity.get("basis") == "cpu"

        # Match config values
        matches_cfg = False
        if current_instances is not None and target_utilization is not None:
            ci_ok = capacity.get("current_instances") == int(current_instances)
            tu_ok = float_equals(float(capacity.get("target_utilization")), float(target_utilization))
            matches_cfg = ci_ok and tu_ok
        checks["capacity_matches_config"] = matches_cfg

        # target_util in (0,1]
        tu = capacity.get("target_utilization")
        checks["capacity_target_util_range"] = is_number(tu) and (0.0 < float(tu) <= 1.0)

        # needed_instances >= 1
        checks["capacity_needed_instances_valid"] = is_int(capacity.get("needed_instances")) and capacity.get("needed_instances") >= 1

        # action valid
        checks["capacity_action_valid"] = capacity.get("action") in allowed_actions

    # Plan.md validations
    # Headers
    checks["plan_has_headers"] = False
    if plan_text:
        headers_ok = all([
            "# Overview" in plan_text,
            "## Per-Resource Analysis" in plan_text,
            "## Scaling Recommendation" in plan_text,
            "## Risks and Caveats" in plan_text,
            "## Next Steps" in plan_text,
        ])
        checks["plan_has_headers"] = headers_ok

    # Horizon mention
    checks["plan_mentions_horizon"] = False
    if plan_text and horizon is not None:
        # Search for horizon number anywhere in the plan
        checks["plan_mentions_horizon"] = str_contains_number(plan_text, float(horizon))

    # Thresholds mention
    checks["plan_mentions_thresholds"] = False
    if plan_text and scale_up_thr is not None and scale_down_thr is not None:
        has_su = str_contains_number(plan_text, float(scale_up_thr))
        has_sd = str_contains_number(plan_text, float(scale_down_thr))
        checks["plan_mentions_thresholds"] = has_su and has_sd

    # Per-Resource section: require for each resource a line containing the resource name and "Trend:" and a (possibly different) line containing the resource name and "Bursty:"
    checks["plan_per_resource_keywords"] = False
    if plan_text:
        per_res_section = extract_section(plan_text, "## Per-Resource Analysis")
        def has_lines_for_resource(section: str, name: str) -> bool:
            lines = section.splitlines()
            has_trend = any((name in ln and "Trend:" in ln) for ln in lines)
            has_bursty = any((name in ln and "Bursty:" in ln) for ln in lines)
            return has_trend and has_bursty
        if all(has_lines_for_resource(per_res_section, n) for n in ["CPU", "Memory", "Requests"]):
            checks["plan_per_resource_keywords"] = True

    # Scaling behavior lines with digits
    checks["plan_has_scaling_behavior_lines"] = False
    if plan_text:
        has_scale_up_freq = re.search(r"Scale-up frequency:\s*\d", plan_text) is not None
        has_avg_interval = re.search(r"Average interval:\s*\d", plan_text) is not None
        checks["plan_has_scaling_behavior_lines"] = has_scale_up_freq and has_avg_interval

    # Compute reward
    # Collect all check keys
    all_check_keys = list(checks.keys())

    # No-op baseline: if any required artifact missing or JSON invalid for required JSONs, reward = 0.0
    required_ok = (
        checks.get("predictions_exists", False)
        and checks.get("capacity_exists", False)
        and checks.get("plan_exists", False)
        and checks.get("predictions_json_valid", False)
        and checks.get("capacity_json_valid", False)
    )

    if not required_ok:
        reward = 0.0
    else:
        # Reward is fraction of passed checks
        passed = sum(1 for k, v in checks.items() if v is True)
        total = len(checks)
        reward = passed / total if total > 0 else 0.0
        # Clamp [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()