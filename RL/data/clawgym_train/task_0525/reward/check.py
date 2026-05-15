import json
import os
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        "log_run_ok": False,
        "log_check_ok": False,
        "log_analyze_ok": False,
        "log_compare_ok": False,
        "stats_ok": False,
        "report_ok": False,
    }

    # Helper to read file content
    def read_file(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    # 1) Verify logs with required IDs
    run_log_path = os.path.join(output_dir, "log_run.txt")
    check_log_path = os.path.join(output_dir, "log_check.txt")
    analyze_log_path = os.path.join(output_dir, "log_analyze.txt")
    compare_log_path = os.path.join(output_dir, "log_compare.txt")

    run_content = read_file(run_log_path)
    if isinstance(run_content, str):
        if ("RW-101" in run_content) and ("RN-505" in run_content):
            checks["log_run_ok"] = True

    check_content = read_file(check_log_path)
    if isinstance(check_content, str):
        if "CK-202" in check_content:
            checks["log_check_ok"] = True

    analyze_content = read_file(analyze_log_path)
    if isinstance(analyze_content, str):
        if "AN-303" in analyze_content:
            checks["log_analyze_ok"] = True

    compare_content = read_file(compare_log_path)
    if isinstance(compare_content, str):
        if "CM-404" in compare_content:
            checks["log_compare_ok"] = True

    # 2) Verify stats.txt contains header and "Total:"
    stats_path = os.path.join(output_dir, "stats.txt")
    stats_content = read_file(stats_path)
    if isinstance(stats_content, str):
        if "=== Rivalwatch Stats ===" in stats_content and "Total:" in stats_content:
            checks["stats_ok"] = True

    # 3) Verify report.md content requirements
    report_path = os.path.join(output_dir, "report.md")
    report_content = read_file(report_path)
    if isinstance(report_content, str):
        # Competitor names must be present (case-sensitive)
        has_alpha = "AlphaCRM" in report_content
        has_beta = "BetaSuite" in report_content

        # SWOT headings (case-insensitive)
        lower_report = report_content.lower()
        has_strengths = "strengths" in lower_report
        has_weaknesses = "weaknesses" in lower_report
        has_opportunities = "opportunities" in lower_report
        has_threats = "threats" in lower_report

        # Word count between 250 and 900 inclusive (split on whitespace)
        words = report_content.split()
        wc_ok = 250 <= len(words) <= 900

        if (has_alpha and has_beta and has_strengths and has_weaknesses and has_opportunities and has_threats and wc_ok):
            checks["report_ok"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0
    # Clamp to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()