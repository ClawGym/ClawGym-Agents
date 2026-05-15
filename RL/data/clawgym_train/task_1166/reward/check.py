import json
import os
import sys

def approx_equal(val, target, tol):
    try:
        return abs(float(val) - float(target)) <= tol
    except Exception:
        return False

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_result_json": False,
        "valid_json_schema": False,
        "level_L4": False,
        "price_position_above_avg": False,
        "rating_position_above_avg": False,
        "avg_price_correct": False,
        "avg_rating_correct": False,
        "pain_points_expected": False,
        "selling_points_expected": False,
        "positioning_premium": False,
        "opportunities_price_high": False,
        "opportunities_quality_high": False,
        "opportunities_count_matches": False,
        "has_report_md": False,
    }

    # Paths
    result_json_path = os.path.join(output_dir, "result.json")
    report_md_path = os.path.join(output_dir, "differentiation_report.md")

    # Check report exists and non-empty
    if os.path.isfile(report_md_path):
        try:
            if os.path.getsize(report_md_path) > 0:
                checks["has_report_md"] = True
        except Exception:
            checks["has_report_md"] = False

    # Load result.json
    if os.path.isfile(result_json_path):
        data, err = load_json_file(result_json_path)
        if data is not None and isinstance(data, dict):
            checks["has_result_json"] = True

            # Validate required top-level keys
            required_top = [
                "level",
                "comparison_matrix",
                "pain_points",
                "selling_points",
                "positioning",
                "diff_opportunities",
                "opportunities_count",
            ]
            top_ok = all(k in data for k in required_top)
            # Validate sub-keys if present
            cm_ok = False
            pos_ok = False
            if top_ok:
                cm = data.get("comparison_matrix", {})
                cm_ok = isinstance(cm, dict) and all(
                    k in cm for k in ["price_position", "rating_position", "avg_price", "avg_rating"]
                )
                positioning = data.get("positioning", {})
                pos_ok = isinstance(positioning, dict) and "position_type" in positioning

            lists_ok = isinstance(data.get("pain_points"), list) and isinstance(data.get("selling_points"), list) and isinstance(data.get("diff_opportunities"), list)

            if top_ok and cm_ok and pos_ok and lists_ok:
                checks["valid_json_schema"] = True

                # Level check
                if data.get("level") == "L4":
                    checks["level_L4"] = True

                # Comparison matrix checks
                cm = data.get("comparison_matrix", {})
                if cm:
                    if cm.get("price_position") == "above_avg":
                        checks["price_position_above_avg"] = True
                    if cm.get("rating_position") == "above_avg":
                        checks["rating_position_above_avg"] = True
                    if approx_equal(cm.get("avg_price"), 49.99, 0.05):
                        checks["avg_price_correct"] = True
                    if approx_equal(cm.get("avg_rating"), 4.40, 0.01):
                        checks["avg_rating_correct"] = True

                # Pain points expected
                # Required: shipping=5 (high), quality=2 (medium), function=1 (low), design=1 (low), value=1 (low)
                required_pain = {
                    ("shipping", 5, "high"),
                    ("quality", 2, "medium"),
                    ("function", 1, "low"),
                    ("design", 1, "low"),
                    ("value", 1, "low"),
                }
                pains = data.get("pain_points", [])
                found_pain = set()
                if isinstance(pains, list):
                    for p in pains:
                        try:
                            cat = p.get("category")
                            freq = p.get("frequency")
                            sev = p.get("severity")
                            if isinstance(cat, str) and isinstance(freq, int) and isinstance(sev, str):
                                key = (cat, freq, sev)
                                if key in required_pain:
                                    found_pain.add(key)
                        except Exception:
                            continue
                if required_pain.issubset(found_pain):
                    checks["pain_points_expected"] = True

                # Selling points expected
                # Required: quality=2 (medium), function=2 (medium), design=1 (weak), value=1 (weak), service=1 (weak)
                required_sell = {
                    ("quality", 2, "medium"),
                    ("function", 2, "medium"),
                    ("design", 1, "weak"),
                    ("value", 1, "weak"),
                    ("service", 1, "weak"),
                }
                sells = data.get("selling_points", [])
                found_sell = set()
                if isinstance(sells, list):
                    for s in sells:
                        try:
                            cat = s.get("category")
                            freq = s.get("frequency")
                            strength = s.get("strength")
                            if isinstance(cat, str) and isinstance(freq, int) and isinstance(strength, str):
                                key = (cat, freq, strength)
                                if key in required_sell:
                                    found_sell.add(key)
                        except Exception:
                            continue
                if required_sell.issubset(found_sell):
                    checks["selling_points_expected"] = True

                # Positioning premium
                pos = data.get("positioning", {})
                if isinstance(pos, dict) and pos.get("position_type") == "premium":
                    checks["positioning_premium"] = True

                # Opportunities checks
                opps = data.get("diff_opportunities", [])
                if isinstance(opps, list):
                    has_price_high = any(
                        isinstance(o, dict) and o.get("angle") == "price" and o.get("priority") == "high"
                        for o in opps
                    )
                    has_quality_high = any(
                        isinstance(o, dict) and o.get("angle") == "quality" and o.get("priority") == "high"
                        for o in opps
                    )
                    if has_price_high:
                        checks["opportunities_price_high"] = True
                    if has_quality_high:
                        checks["opportunities_quality_high"] = True

                    try:
                        if int(data.get("opportunities_count")) == len(opps):
                            checks["opportunities_count_matches"] = True
                    except Exception:
                        checks["opportunities_count_matches"] = False

    # Compute reward
    # Enforce no-op baseline: if either required artifact missing, reward = 0.0
    if not (checks["has_result_json"] and checks["has_report_md"]):
        reward = 0.0
    else:
        # Average over all boolean checks
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Ensure reward in [0,1]
        reward = passed / total if total > 0 else 0.0

    # Print final JSON metrics
    result_obj = {"reward": round(reward, 6)}
    result_obj.update(checks)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()