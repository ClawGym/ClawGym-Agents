import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def extract_function_block(text, def_name):
    # Rough extraction of a Python function block by indentation
    # Returns the function block string if found, else None
    lines = text.splitlines()
    start_idx = None
    base_indent = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"def {def_name}("):
            start_idx = i
            base_indent = len(line) - len(stripped)
            break
    if start_idx is None:
        return None
    block_lines = [lines[start_idx]]
    for j in range(start_idx + 1, len(lines)):
        l = lines[j]
        if l.strip() == "":
            block_lines.append(l)
            continue
        indent = len(l) - len(l.lstrip())
        # End of function if next def/class at same or lower indent
        if l.lstrip().startswith("def ") or l.lstrip().startswith("class "):
            if indent <= base_indent:
                break
        block_lines.append(l)
    return "\n".join(block_lines)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # buggy_module_fixed.py checks
        "has_bugfix_file": False,
        "has_is_leap_def": False,
        "fixed_leap_logic": False,
        "has_days_in_month": False,
        "days_calls_is_leap_year": False,
        # validation.json checks
        "validation_exists": False,
        "validation_cases_count_correct": False,
        "validation_cases_set_correct": False,
        "validation_cases_fields_types": False,
        "validation_predictions_match": False,
        # progress L1 checks
        "l1_exists": False,
        "l1_sections_present": False,
        # triage L2 checks
        "l2_exists": False,
        "l2_contains_error_text": False,
        "l2_contains_code_context": False,
        # escalation L3 checks
        "l3_exists": False,
        "l3_has_title": False,
        "l3_sections_present": False,
        "l3_has_checklist_section": False,
        "l3_checklist_items_complete": False,
        "l3_adjacent_risk_mention": False,
    }

    # 1) Check buggy_module_fixed.py
    fixed_path = os.path.join(output_dir, "buggy_module_fixed.py")
    if os.path.isfile(fixed_path):
        checks["has_bugfix_file"] = True
        content = read_text(fixed_path) or ""
        # def is_leap_year present
        if "def is_leap_year(" in content:
            checks["has_is_leap_def"] = True
        # Ensure leap-year logic substrings present
        has_div4 = "year % 4 == 0" in content
        has_not_div100 = "year % 100 != 0" in content
        has_div400 = "year % 400 == 0" in content
        wrong_pattern = "year % 4 == 0 and year % 100 == 0" in content
        # Reject if wrong pattern and missing 400 exception
        if has_div4 and has_not_div100 and has_div400:
            if not (wrong_pattern and not has_div400):
                checks["fixed_leap_logic"] = True
        # def days_in_month present
        if "def days_in_month(" in content:
            checks["has_days_in_month"] = True
            block = extract_function_block(content, "days_in_month")
            if block and "is_leap_year(" in block:
                checks["days_calls_is_leap_year"] = True

    # 2) Check validation.json
    validation_path = os.path.join(output_dir, "validation.json")
    required_cases = {
        1996: True,
        1900: False,
        2000: True,
        2023: False,
    }
    if os.path.isfile(validation_path):
        checks["validation_exists"] = True
        try:
            with open(validation_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "cases" in data and isinstance(data["cases"], list):
                cases = data["cases"]
                if len(cases) == 4:
                    checks["validation_cases_count_correct"] = True
                years = []
                fields_types_ok = True
                pred_matches = True
                for c in cases:
                    if not isinstance(c, dict):
                        fields_types_ok = False
                        break
                    if not all(k in c for k in ("year", "expected", "predicted")):
                        fields_types_ok = False
                        break
                    if not isinstance(c["year"], int):
                        fields_types_ok = False
                        break
                    if not isinstance(c["expected"], bool) or not isinstance(c["predicted"], bool):
                        fields_types_ok = False
                        break
                    years.append(c["year"])
                if fields_types_ok:
                    checks["validation_cases_fields_types"] = True
                    if set(years) == set(required_cases.keys()):
                        checks["validation_cases_set_correct"] = True
                        # Check predictions match expected per required cases
                        by_year = {c["year"]: c for c in cases}
                        for y, exp in required_cases.items():
                            if by_year[y]["expected"] != exp or by_year[y]["predicted"] != exp:
                                pred_matches = False
                                break
                        if pred_matches:
                            checks["validation_predictions_match"] = True
        except Exception:
            # parsing error -> remain False
            pass

    # 3) progress_l1.md
    l1_path = os.path.join(output_dir, "progress_l1.md")
    if os.path.isfile(l1_path):
        checks["l1_exists"] = True
        l1 = read_text(l1_path) or ""
        required_labels = [
            "Objective:",
            "Current hypothesis:",
            "Actions executed:",
            "Evidence observed:",
            "Decision:",
            "Next step:",
        ]
        if all(lbl in l1 for lbl in required_labels):
            checks["l1_sections_present"] = True

    # 4) triage_l2.md
    l2_path = os.path.join(output_dir, "triage_l2.md")
    if os.path.isfile(l2_path):
        checks["l2_exists"] = True
        l2 = read_text(l2_path) or ""
        if "AssertionError: assert True is False" in l2:
            checks["l2_contains_error_text"] = True
        if "def is_leap_year(" in l2:
            checks["l2_contains_code_context"] = True

    # 5) escalation_l3.md
    l3_path = os.path.join(output_dir, "escalation_l3.md")
    if os.path.isfile(l3_path):
        checks["l3_exists"] = True
        l3 = read_text(l3_path) or ""
        l3_lower = l3.lower()

        # Title phrase
        if "bounded escalation report" in l3_lower:
            checks["l3_has_title"] = True

        # Sections
        required_sections = [
            "facts established",
            "options eliminated",
            "smallest unresolved uncertainty",
            "required external dependency",
            "recommendation",
        ]
        if all(sec in l3_lower for sec in required_sections):
            checks["l3_sections_present"] = True

        # Checklist section phrase
        if "7-point checklist evidence" in l3_lower:
            checks["l3_has_checklist_section"] = True

        # Checklist items as markdown checkboxes
        lines = [ln.strip().lower() for ln in l3.splitlines()]
        checkbox_lines = [ln for ln in lines if ln.startswith("- [") and "]" in ln]
        required_items = [
            "exact error captured",
            "relevant context read",
            "runtime prerequisites verified",
            "materially different approach tried",
            "pass/fail criteria defined",
            "validation executed",
            "adjacent risk scanned",
        ]
        item_presence = {item: False for item in required_items}
        for item in required_items:
            for ln in checkbox_lines:
                if item in ln:
                    item_presence[item] = True
                    break
        if all(item_presence.values()):
            checks["l3_checklist_items_complete"] = True

        # Adjacent risk mention
        if "adjacent risk" in l3_lower:
            checks["l3_adjacent_risk_mention"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward is exactly 0.0 when output is empty or missing core artifacts
    # Core artifacts are the five required files
    core_files = [
        fixed_path,
        validation_path,
        l1_path,
        l2_path,
        l3_path,
    ]
    if not any(os.path.isfile(p) for p in core_files):
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()