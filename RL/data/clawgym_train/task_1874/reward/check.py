import json
import os
import sys
import csv

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def number_to_int_if_whole(x):
    if isinstance(x, int):
        return x, True
    if isinstance(x, float) and x.is_integer():
        return int(x), True
    return None, False

def compute_expected_rate_str(errors, total):
    try:
        e = float(errors)
        t = float(total)
    except Exception:
        return None
    if t <= 0:
        rate = 0.0
    else:
        rate = (e / t) * 100.0
    return f"{rate:.2f}%"

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_summary_json": False,
        "summary_schema_valid": False,
        "period_15m": False,
        "error_rate_matches": False,
        "top_errors_shape_valid": False,
        "top_errors_sorted": False,
        "has_errors_csv": False,
        "errors_csv_header": False,
        "errors_csv_two_columns": False,
        "errors_csv_rowcount_matches": False,
        "errors_csv_all_error": False,
        "has_patterns_md": False,
        "patterns_min_length": False,
        "patterns_contains_theme": False,
    }

    summary_path = os.path.join(output_dir, "summary.json")
    errors_csv_path = os.path.join(output_dir, "errors.csv")
    patterns_md_path = os.path.join(output_dir, "patterns.md")

    summary = None

    # Check summary.json existence and schema
    if os.path.isfile(summary_path):
        checks["has_summary_json"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception:
            summary = None

        if isinstance(summary, dict):
            required_keys = ["period", "total", "errors", "warnings", "errorRate", "topErrors"]
            has_keys = all(k in summary for k in required_keys)
            types_ok = (
                isinstance(summary.get("period"), str) and
                is_number(summary.get("total")) and
                is_number(summary.get("errors")) and
                is_number(summary.get("warnings")) and
                isinstance(summary.get("errorRate"), str) and
                isinstance(summary.get("topErrors"), list)
            )
            checks["summary_schema_valid"] = has_keys and types_ok

            # period exact "15m"
            if checks["summary_schema_valid"] and summary.get("period") == "15m":
                checks["period_15m"] = True

            # errorRate correctness
            if checks["summary_schema_valid"]:
                expected_rate = compute_expected_rate_str(summary["errors"], summary["total"])
                if expected_rate is not None and summary["errorRate"] == expected_rate:
                    checks["error_rate_matches"] = True

            # topErrors shape and sorted by count desc
            if checks["summary_schema_valid"]:
                top_errors = summary.get("topErrors", [])
                shape_ok = isinstance(top_errors, list) and len(top_errors) <= 5
                sorted_ok = False
                if shape_ok:
                    prev = None
                    per_item_ok = True
                    for item in top_errors:
                        if not (isinstance(item, dict) and "message" in item and "count" in item):
                            per_item_ok = False
                            break
                        if not (isinstance(item["message"], str) and is_number(item["count"])):
                            per_item_ok = False
                            break
                    if per_item_ok:
                        counts = [float(it["count"]) for it in top_errors]
                        sorted_ok = all(counts[i] >= counts[i+1] for i in range(len(counts)-1))
                        shape_ok = True
                    else:
                        shape_ok = False
                checks["top_errors_shape_valid"] = shape_ok
                checks["top_errors_sorted"] = sorted_ok

    # Check errors.csv existence and content
    if os.path.isfile(errors_csv_path):
        checks["has_errors_csv"] = True
        try:
            with open(errors_csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            rows = None

        if rows is not None and len(rows) >= 1:
            header = rows[0]
            if header == ["severity", "message"]:
                checks["errors_csv_header"] = True

            # Validate row columns, severity values, and count matches summary.errors
            data_rows = rows[1:]
            # two columns check
            if all(len(r) == 2 for r in data_rows):
                checks["errors_csv_two_columns"] = True

            if all(len(r) >= 1 and r[0] == "error" for r in data_rows):
                checks["errors_csv_all_error"] = True

            # Row count compare to summary.errors (integer-like)
            if summary is not None and checks["summary_schema_valid"]:
                err_val = summary["errors"]
                err_int, is_int_like = number_to_int_if_whole(err_val)
                if is_int_like and err_int == len(data_rows):
                    checks["errors_csv_rowcount_matches"] = True

    # Check patterns.md existence and content requirements
    if os.path.isfile(patterns_md_path):
        checks["has_patterns_md"] = True
        try:
            with open(patterns_md_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = ""
        if isinstance(content, str):
            if len(content.strip()) >= 120:
                checks["patterns_min_length"] = True
            low = content.lower()
            if ("timeout" in low) or ("rate limit" in low) or ("file not found" in low):
                checks["patterns_contains_theme"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()