import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="latin-1") as f:
                return f.read()
        except Exception:
            return None

def validate_summary_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False, False
    # Validate top-level keys and types
    required_top = ["total_violations", "counts", "asil", "rules"]
    for k in required_top:
        if k not in data:
            return True, False
    if not isinstance(data["total_violations"], int):
        return True, False
    if not isinstance(data["counts"], dict):
        return True, False
    if not isinstance(data["asil"], dict):
        return True, False
    if not isinstance(data["rules"], list):
        return True, False
    # counts keys
    for k in ["Mandatory", "Required", "Advisory"]:
        if k not in data["counts"] or not isinstance(data["counts"][k], int):
            return True, False
    # asil keys
    for k in ["A", "B", "C", "D", "Not mapped"]:
        if k not in data["asil"] or not isinstance(data["asil"][k], int):
            return True, False
    # rules entries must be strings
    if not all(isinstance(x, str) for x in data["rules"]):
        return True, False
    # must include "15.1" and "21.3"
    has_required_rules = ("15.1" in data["rules"]) and ("21.3" in data["rules"])
    return True, has_required_rules

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "report_exists": False,
        "report_has_violation_block": False,
        "report_has_rule_15_1": False,
        "report_has_rule_21_3": False,
        "report_has_review_summary": False,
        "fixed_module_exists": False,
        "fixed_no_banned_substrings": False,
        "fixed_has_fixed_width_type": False,
        "fixed_has_switch_default": False,
        "summary_json_exists": False,
        "summary_json_valid": False,
        "summary_rules_include_15_1_and_21_3": False,
    }

    # Check report.md
    report_path = os.path.join(output_dir, "report.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        content = read_text(report_path)
        if isinstance(content, str):
            if "VIOLATION #1" in content:
                checks["report_has_violation_block"] = True
            if "Rule        : MISRA C:2012 Rule 15.1" in content:
                checks["report_has_rule_15_1"] = True
            if "Rule        : MISRA C:2012 Rule 21.3" in content:
                checks["report_has_rule_21_3"] = True
            # Must include REVIEW SUMMARY and Overall compliance status:
            if ("REVIEW SUMMARY" in content) and ("Overall compliance status:" in content):
                checks["report_has_review_summary"] = True

    # Check fixed_module.txt
    fixed_path = os.path.join(output_dir, "fixed_module.txt")
    if os.path.isfile(fixed_path):
        checks["fixed_module_exists"] = True
        fcontent = read_text(fixed_path)
        if isinstance(fcontent, str):
            banned = ["goto", "malloc", "calloc", "realloc", "free"]
            if all(b not in fcontent for b in banned):
                checks["fixed_no_banned_substrings"] = True
            fixed_width_tokens = [
                "uint8_t", "uint16_t", "uint32_t", "uint64_t",
                "int8_t", "int16_t", "int32_t", "int64_t",
                "bool"
            ]
            if any(tok in fcontent for tok in fixed_width_tokens):
                checks["fixed_has_fixed_width_type"] = True
            if "default:" in fcontent:
                checks["fixed_has_switch_default"] = True

    # Check summary.json
    summary_path = os.path.join(output_dir, "summary.json")
    if os.path.isfile(summary_path):
        checks["summary_json_exists"] = True
        valid, has_rules = validate_summary_json(summary_path)
        if valid:
            checks["summary_json_valid"] = True
        if has_rules:
            checks["summary_rules_include_15_1_and_21_3"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure no-op baseline: if no output directory or empty with no required artifacts, reward 0.0 naturally
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()