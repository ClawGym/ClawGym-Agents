import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
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
        "spec_sections_ok": False,
        "plan_has_numbered_and_verification": False,
        "risk_review_answers": False,
        "report_py_has_function": False,
        "cli_has_args": False,
        "test_references_generate_report": False,
        "demo_json_valid_structure": False,
        "verify_has_confirmation": False,
        "superpowers_status_enabled_true": False,
    }

    # 1) output/spec.md sections
    spec_path = os.path.join(output_dir, "spec.md")
    spec_text = read_text(spec_path)
    if spec_text is not None and spec_text.strip():
        lt = spec_text.lower()
        sections = ["goal", "non-goals", "constraints", "acceptance criteria", "risks"]
        if all(s in lt for s in sections):
            checks["spec_sections_ok"] = True

    # 2) output/plan.md numbered list and "Verification gates:"
    plan_path = os.path.join(output_dir, "plan.md")
    plan_text = read_text(plan_path)
    if plan_text is not None and plan_text.strip():
        lines = plan_text.splitlines()
        has_numbered = any(l.strip().startswith("1.") for l in lines)
        has_verification = "verification gates:" in plan_text.lower()
        if has_numbered and has_verification:
            checks["plan_has_numbered_and_verification"] = True

    # 3) output/risk-review.md with phrases
    rr_path = os.path.join(output_dir, "risk-review.md")
    rr_text = read_text(rr_path)
    if rr_text is not None and rr_text.strip():
        lt = rr_text.lower()
        if ("how can this fail" in lt) and ("weakest" in lt) and ("rollback" in lt):
            checks["risk_review_answers"] = True

    # 4) output/src/report.py function definition
    report_py_path = os.path.join(output_dir, "src", "report.py")
    report_py_text = read_text(report_py_path)
    if report_py_text is not None and "def generate_report(" in report_py_text:
        checks["report_py_has_function"] = True

    # 5) output/src/cli.py argparse and flags
    cli_py_path = os.path.join(output_dir, "src", "cli.py")
    cli_py_text = read_text(cli_py_path)
    if cli_py_text is not None and cli_py_text.strip():
        lt = cli_py_text.lower()
        if ("argparse" in lt) and ("--input" in lt) and ("--output" in lt):
            checks["cli_has_args"] = True

    # 6) output/tests/test_report.py references generate_report(
    test_path = os.path.join(output_dir, "tests", "test_report.py")
    test_text = read_text(test_path)
    if test_text is not None and "generate_report(" in test_text:
        checks["test_references_generate_report"] = True

    # 7) output/demo/report.json structural checks
    demo_json_path = os.path.join(output_dir, "demo", "report.json")
    try:
        with open(demo_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        has_monthly = isinstance(data, dict) and "monthly" in data and isinstance(data["monthly"], dict)
        has_overall = isinstance(data, dict) and "overall" in data and isinstance(data["overall"], dict)
        overall_total_ok = has_overall and ("total" in data["overall"]) and is_number(data["overall"]["total"])
        month_key_ok = False
        month_obj_ok = False
        if has_monthly:
            pattern = re.compile(r"^\d{4}-\d{2}$")
            for k, v in data["monthly"].items():
                if isinstance(k, str) and pattern.match(k):
                    month_key_ok = True
                    if isinstance(v, dict):
                        if ("categories" in v and isinstance(v["categories"], dict)
                                and "total" in v and is_number(v["total"])):
                            month_obj_ok = True
                            break
        if has_monthly and has_overall and overall_total_ok and month_key_ok and month_obj_ok:
            checks["demo_json_valid_structure"] = True
    except Exception:
        # Leave as False if any error
        pass

    # 8) output/verify.md contains "Verified" or "Pass"
    verify_path = os.path.join(output_dir, "verify.md")
    verify_text = read_text(verify_path)
    if verify_text is not None and verify_text.strip():
        lt = verify_text.lower()
        if ("verified" in lt) or ("pass" in lt):
            checks["verify_has_confirmation"] = True

    # 9) output/superpowers-status.txt contains "enabled" and "true"
    sp_status_path = os.path.join(output_dir, "superpowers-status.txt")
    sp_text = read_text(sp_status_path)
    if sp_text is not None and sp_text.strip():
        lt = sp_text.lower()
        if ("enabled" in lt) and ("true" in lt):
            checks["superpowers_status_enabled_true"] = True

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()