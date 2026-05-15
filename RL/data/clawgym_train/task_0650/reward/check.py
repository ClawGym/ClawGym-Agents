import json
import os
import sys
from typing import Dict, Any

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def parse_csv_line(line: str):
    return [part.strip() for part in line.rstrip("\n").split(",")]

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks to False
    checks: Dict[str, bool] = {
        # 1) logs existence and content markers
        "logs_py_sum_exists": False,
        "logs_py_genexpr_exists": False,
        "logs_py_sum_has_stats_markers": False,
        "logs_py_genexpr_has_stats_markers": False,
        # 2) compare existence and content
        "compare_exists": False,
        "compare_has_required_markers": False,
        # 3) summary.json validations
        "summary_exists": False,
        "summary_valid_json": False,
        "summary_has_required_keys": False,
        "summary_has_benchmark_keys": False,
        "summary_stats_positive_numbers": False,
        "summary_faster_label_valid": False,
        "summary_speed_ratio_valid": False,
        # 4) CSV validations
        "csv_exists": False,
        "csv_header_correct": False,
        "csv_has_two_rows": False,
        "csv_labels_correct": False,
        "csv_metrics_numeric_positive": False,
        # 5) report validations
        "report_exists": False,
        "report_has_headings": False,
        "report_mentions_input_files": False,
        "report_mentions_mean_median": False,
    }

    # Paths
    log_sum_path = os.path.join(output_dir, "logs", "py_sum.txt")
    log_genexpr_path = os.path.join(output_dir, "logs", "py_genexpr.txt")
    compare_path = os.path.join(output_dir, "compare.txt")
    summary_path = os.path.join(output_dir, "summary.json")
    csv_path = os.path.join(output_dir, "tables", "summary.csv")
    report_path = os.path.join(output_dir, "report.md")

    # Check logs existence
    if os.path.isfile(log_sum_path):
        checks["logs_py_sum_exists"] = True
        content = read_text(log_sum_path)
        required_markers = ["Results:", "Mean:", "Median:", "Min:", "Max:", "StdDev:"]
        if all(m in content for m in required_markers):
            checks["logs_py_sum_has_stats_markers"] = True

    if os.path.isfile(log_genexpr_path):
        checks["logs_py_genexpr_exists"] = True
        content = read_text(log_genexpr_path)
        required_markers = ["Results:", "Mean:", "Median:", "Min:", "Max:", "StdDev:"]
        if all(m in content for m in required_markers):
            checks["logs_py_genexpr_has_stats_markers"] = True

    # Check compare.txt
    if os.path.isfile(compare_path):
        checks["compare_exists"] = True
        content = read_text(compare_path)
        lines = content.splitlines()
        has_comparison_header = any(l.lstrip().startswith("Comparison (") for l in lines)
        avg_count = content.count("avg (")
        if has_comparison_header and avg_count >= 2:
            checks["compare_has_required_markers"] = True

    # Check summary.json
    summary_data: Dict[str, Any] = {}
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_data = json.load(f)
            checks["summary_valid_json"] = isinstance(summary_data, dict)
        except Exception:
            summary_data = {}

    if checks["summary_valid_json"]:
        top_keys_ok = all(k in summary_data for k in ["benchmarks", "faster_label", "speed_ratio"])
        if top_keys_ok:
            checks["summary_has_required_keys"] = True

            benches = summary_data.get("benchmarks")
            if isinstance(benches, dict) and "py_sum" in benches and "py_genexpr" in benches:
                checks["summary_has_benchmark_keys"] = True

                stats_ok = True
                for label in ["py_sum", "py_genexpr"]:
                    stats = benches.get(label)
                    if not isinstance(stats, dict):
                        stats_ok = False
                        break
                    for metric in ["mean", "median", "min", "max", "stddev"]:
                        val = stats.get(metric, None)
                        if not is_number(val) or val <= 0:
                            stats_ok = False
                            break
                    if not stats_ok:
                        break
                if stats_ok:
                    checks["summary_stats_positive_numbers"] = True

            fl = summary_data.get("faster_label")
            if fl in ("py_sum", "py_genexpr"):
                checks["summary_faster_label_valid"] = True

            sr = summary_data.get("speed_ratio")
            if is_number(sr) and sr >= 1:
                checks["summary_speed_ratio_valid"] = True

    # Check CSV
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f.readlines()]
            # Remove trailing empty lines for robust counting
            while lines and lines[-1].strip() == "":
                lines.pop()
            if lines:
                header = lines[0].strip()
                if header == "label,mean,median,min,max,stddev":
                    checks["csv_header_correct"] = True
                data_rows = [ln for ln in lines[1:] if ln.strip() != ""]
                if len(data_rows) == 2:
                    checks["csv_has_two_rows"] = True
                    # Validate labels and numeric values
                    parsed = [parse_csv_line(r) for r in data_rows]
                    labels = {row[0] for row in parsed if len(row) >= 6}
                    if labels == {"py_sum", "py_genexpr"}:
                        checks["csv_labels_correct"] = True
                    numeric_ok = True
                    for row in parsed:
                        if len(row) != 6:
                            numeric_ok = False
                            break
                        # columns: 1..5 should be numeric > 0
                        for i in range(1, 6):
                            try:
                                v = float(row[i])
                                if not (v > 0):
                                    numeric_ok = False
                                    break
                            except Exception:
                                numeric_ok = False
                                break
                        if not numeric_ok:
                            break
                    if numeric_ok:
                        checks["csv_metrics_numeric_positive"] = True
        except Exception:
            pass

    # Check report.md
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        content = read_text(report_path)
        lines = [ln.strip() for ln in content.splitlines()]
        headings_required = {"## Methodology", "## Findings", "## Recommendation", "## Reproduction"}
        headings_present = set(h for h in headings_required if h in lines)
        if headings_present == headings_required:
            checks["report_has_headings"] = True
        # Mentions of input files
        mentions_files = ("input/py_sum.py" in content) and ("input/py_genexpr.py" in content)
        if mentions_files:
            checks["report_mentions_input_files"] = True
        # Contains the words "mean" and "median" (case-insensitive)
        lower = content.lower()
        if ("mean" in lower) and ("median" in lower):
            checks["report_mentions_mean_median"] = True

    # Compute reward as average of check booleans
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty relevant artifacts, reward remains based on checks (which will be 0.0 if nothing exists)
    result = {"reward": float(reward)}
    result.update(checks)

    # Print exactly one JSON object on the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()