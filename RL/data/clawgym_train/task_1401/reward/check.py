import json
import os
import sys
import csv

def is_number(x):
    try:
        float(x)
        return True
    except Exception:
        return False

def in_01(x):
    try:
        v = float(x)
        return 0.0 <= v <= 1.0
    except Exception:
        return False

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def parse_csv(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows, None
    except Exception as e:
        return None, str(e)

def get_nested(d, *keys):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "report_exists": False,
        "report_json_valid": False,
        "report_has_required_slices": False,
        "report_counts_valid": False,
        "report_rates_present_and_in_range": False,
        "report_blind_spots_present": False,

        "metrics_exists": False,
        "metrics_header_ok": False,
        "metrics_has_rows_for_all_slices": False,
        "metrics_cells_valid": False,

        "human_plan_exists": False,
        "human_plan_has_required_phrases": False,

        "gates_exists": False,
        "gates_json_valid": False,
        "gates_thresholds_cover_required_metrics_in_range": False,
        "gates_status_valid": False,
        "gates_rollback_criteria_present": False,
        "gates_status_consistent_with_report": False,
    }

    # Paths
    report_path = os.path.join(output_dir, "report.json")
    metrics_path = os.path.join(output_dir, "metrics.csv")
    human_plan_path = os.path.join(output_dir, "human_eval_plan.md")
    gates_path = os.path.join(output_dir, "gates.json")

    # 1) report.json checks
    report = None
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report, err = read_json(report_path)
        if report is not None and isinstance(report, dict):
            checks["report_json_valid"] = True

            # dataset_version string and slices exist
            slices = report.get("slices")
            required_slices = ["invoice", "im_formatting", "math_slop"]
            if isinstance(slices, dict) and all(s in slices for s in required_slices) and isinstance(report.get("dataset_version"), str):
                checks["report_has_required_slices"] = True

                # counts valid
                counts_ok = True
                for s in required_slices:
                    count_val = slices[s].get("count")
                    if not isinstance(count_val, int) or count_val < 1:
                        counts_ok = False
                        break
                checks["report_counts_valid"] = counts_ok

                # rates present and in [0,1]
                rate_keys = {
                    "invoice": ["exact_total_match_rate", "currency_symbol_ok_rate", "json_valid_rate"],
                    "im_formatting": ["no_markdown_symbol_rate", "table_to_list_ok_rate"],
                    "math_slop": ["latex_valid_rate", "trivial_identity_rate"],
                }
                rates_ok = True
                for s in required_slices:
                    if not isinstance(slices.get(s), dict):
                        rates_ok = False
                        break
                    for rk in rate_keys[s]:
                        val = slices[s].get(rk)
                        if not (isinstance(val, (int, float)) and 0.0 <= float(val) <= 1.0):
                            rates_ok = False
                            break
                    if not rates_ok:
                        break
                checks["report_rates_present_and_in_range"] = rates_ok

            # blind_spots
            blind_spots = report.get("blind_spots")
            if isinstance(blind_spots, list) and len(blind_spots) >= 3:
                checks["report_blind_spots_present"] = True
        else:
            checks["report_json_valid"] = False

    # 2) metrics.csv checks
    rows = None
    expected_header = [
        "slice",
        "id",
        "exact_total_match",
        "currency_symbol_ok",
        "json_valid",
        "no_markdown_symbols",
        "table_to_list_ok",
        "latex_valid",
        "trivial_identity_ok",
    ]
    if os.path.isfile(metrics_path):
        checks["metrics_exists"] = True
        rows, err = parse_csv(metrics_path)
        if rows and len(rows) >= 2:
            header = rows[0]
            if header == expected_header:
                checks["metrics_header_ok"] = True

                # at least one row for each slice
                present_slices = set()
                cell_values_ok = True
                allowed_slices = {"invoice", "im_formatting", "math_slop"}
                metric_cols = expected_header[2:]
                for r in rows[1:]:
                    # Require exact number of columns
                    if len(r) != len(expected_header):
                        cell_values_ok = False
                        break
                    slice_val = r[0].strip()
                    id_val = r[1].strip()
                    if slice_val in allowed_slices:
                        present_slices.add(slice_val)
                    else:
                        cell_values_ok = False
                        break
                    if id_val == "":
                        cell_values_ok = False
                        break
                    # Validate metric cells
                    for idx, col in enumerate(metric_cols, start=2):
                        v = r[idx].strip()
                        if v not in ("", "0", "1"):
                            cell_values_ok = False
                            break
                    if not cell_values_ok:
                        break
                if present_slices.issuperset({"invoice", "im_formatting", "math_slop"}):
                    checks["metrics_has_rows_for_all_slices"] = True
                checks["metrics_cells_valid"] = cell_values_ok

    # 3) human_eval_plan.md checks
    if os.path.isfile(human_plan_path):
        checks["human_plan_exists"] = True
        content, err = read_text(human_plan_path)
        if isinstance(content, str):
            required_phrases = ["Sample size:", "Blind A/B", "Rater locale", "Anchors 1-5", "Adjudication"]
            if all(p in content for p in required_phrases):
                checks["human_plan_has_required_phrases"] = True

    # 4) gates.json checks
    gates = None
    if os.path.isfile(gates_path):
        checks["gates_exists"] = True
        gates, err = read_json(gates_path)
        if gates is not None and isinstance(gates, dict):
            checks["gates_json_valid"] = True
            thresholds = gates.get("thresholds")
            status = gates.get("status")
            rollback = gates.get("rollback_criteria")

            # thresholds cover required metrics with values in [0,1]
            required_threshold_keys = [
                "invoice.exact_total_match_rate",
                "im_formatting.no_markdown_symbol_rate",
                "math_slop.latex_valid_rate",
                "math_slop.trivial_identity_rate",
            ]
            th_ok = True
            if not isinstance(thresholds, dict):
                th_ok = False
            else:
                for k in required_threshold_keys:
                    v = thresholds.get(k, None)
                    if not isinstance(v, (int, float)) or not (0.0 <= float(v) <= 1.0):
                        th_ok = False
                        break
            checks["gates_thresholds_cover_required_metrics_in_range"] = th_ok

            # status valid
            if isinstance(status, str) and status in ("pass", "fail"):
                checks["gates_status_valid"] = True

            # rollback criteria present
            if isinstance(rollback, str) and rollback.strip() != "":
                checks["gates_rollback_criteria_present"] = True

            # Cross-check status consistency with report.json
            consistent = False
            if checks["report_json_valid"] and checks["report_has_required_slices"] and checks["report_rates_present_and_in_range"] and th_ok and checks["gates_status_valid"]:
                def rate_from_report(report_obj, dotted_key):
                    # dotted_key like "invoice.exact_total_match_rate"
                    parts = dotted_key.split(".")
                    if len(parts) != 2:
                        return None
                    slice_name, rate_key = parts
                    return get_nested(report_obj, "slices", slice_name, rate_key)

                any_below = False
                for k in required_threshold_keys:
                    rep_rate = rate_from_report(report, k)
                    thr = thresholds.get(k)
                    if rep_rate is None or not isinstance(rep_rate, (int, float)):
                        any_below = True
                        break
                    if float(rep_rate) < float(thr):
                        any_below = True
                        break
                computed_status = "fail" if any_below else "pass"
                if status == computed_status:
                    consistent = True
            checks["gates_status_consistent_with_report"] = consistent

    # Compute reward: average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline: if all output artifacts missing or invalid, reward 0.0 naturally
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()