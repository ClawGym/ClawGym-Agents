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

def first_n_nonempty_lines_have_triple_quote(text, n=5):
    if text is None:
        return False
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    for ln in lines[:n]:
        if '"""' in ln:
            return True
    return False

def contains_case_insensitive(haystack, needle):
    if haystack is None:
        return False
    return needle.lower() in haystack.lower()

def find_line_starting_with(text, prefix):
    if text is None:
        return None, -1
    for idx, line in enumerate(text.splitlines()):
        if line.strip().lower().startswith(prefix.lower()):
            return line, idx
    return None, -1

def list_py_files_under(path):
    result = []
    if not os.path.isdir(path):
        return result
    for root, dirs, files in os.walk(path):
        for fn in files:
            if fn.endswith(".py"):
                result.append(os.path.join(root, fn))
    return result

def load_modified_files(json_path):
    text = read_text(json_path)
    if text is None:
        return False, None
    try:
        data = json.loads(text)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return True, data
        return False, None
    except Exception:
        return False, None

def audit_files_list_contains_two_modified(audit_text, modified_files_list):
    # Requirement: line starting with "Files to review:" and list at least two of the modified file paths.
    if audit_text is None or not modified_files_list:
        return False, False  # (has_line, has_two_files)
    line, idx = find_line_starting_with(audit_text, "Files to review:")
    has_line = line is not None
    if not has_line:
        return False, False
    # Consider this line and next 5 lines as the section where files may be listed
    lines = audit_text.splitlines()
    section = line
    for j in range(1, 6):
        if 0 <= idx + j < len(lines):
            section += " " + lines[idx + j]
    # Count how many modified files appear as substrings in this section
    count = 0
    seen = set()
    for mf in modified_files_list:
        if mf in section and mf not in seen:
            seen.add(mf)
            count += 1
    return True, (count >= 2)

def validate_exit_reason(text):
    # Find line starting with "Exit reason:" and validate value is one of allowed
    if text is None:
        return False
    line, _ = find_line_starting_with(text, "Exit reason:")
    if not line:
        return False
    value = line.split(":", 1)[1].strip() if ":" in line else ""
    allowed = ["clean audit", "low-only round", "loop cap reached"]
    return value.lower() in allowed

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Required files relative to output/
    required_files = [
        "src/text_reports/__init__.py",
        "src/text_reports/report.py",
        "src/text_reports/cli.py",
        "tests/test_report.py",
        "README.md",
        "modified_files.json",
        "report.md",
        "audit/round1_simplify.md",
        "audit/round1_harden.md",
        "audit/round1_spec.md",
    ]

    # Build absolute paths map
    abs_paths = {rf: os.path.join(output_dir, rf) for rf in required_files}

    checks = {}

    # Existence checks
    for rf in required_files:
        key = f"exists_{rf.replace('/', '_').replace('.', '_')}"
        checks[key] = os.path.isfile(abs_paths[rf])

    # Convenience booleans for existence
    exists_report_py = checks["exists_src_text_reports_report_py"]
    exists_init_py = checks["exists_src_text_reports___init___py"]
    exists_cli_py = checks["exists_src_text_reports_cli_py"]
    exists_test_py = checks["exists_tests_test_report_py"]
    exists_readme = checks["exists_README_md"]
    exists_modified = checks["exists_modified_files_json"]
    exists_audit_simplify = checks["exists_audit_round1_simplify_md"]
    exists_audit_harden = checks["exists_audit_round1_harden_md"]
    exists_audit_spec = checks["exists_audit_round1_spec_md"]
    exists_summary = checks["exists_report_md"]

    # Python static checks
    # 1) No TODO/FIXME in required py files (case-insensitive)
    no_todo_fixme_key = "no_todo_fixme_in_required_python_files"
    checks[no_todo_fixme_key] = False
    required_py_abs = []
    if exists_report_py:
        required_py_abs.append(abs_paths["src/text_reports/report.py"])
    if exists_init_py:
        required_py_abs.append(abs_paths["src/text_reports/__init__.py"])
    if exists_cli_py:
        required_py_abs.append(abs_paths["src/text_reports/cli.py"])
    if exists_test_py:
        required_py_abs.append(abs_paths["tests/test_report.py"])
    if len(required_py_abs) == 4:
        ok = True
        for p in required_py_abs:
            txt = read_text(p)
            if txt is None or ("todo" in txt.lower() or "fixme" in txt.lower()):
                ok = False
                break
        checks[no_todo_fixme_key] = ok

    # 2) report.py contains function names
    checks["report_functions_present"] = False
    if exists_report_py:
        rpt = read_text(abs_paths["src/text_reports/report.py"])
        if rpt is not None:
            has_parse = re.search(r"\bdef\s+parse_csv\s*\(", rpt) is not None
            has_compute = re.search(r"\bdef\s+compute_metrics\s*\(", rpt) is not None
            has_render = re.search(r"\bdef\s+render_markdown\s*\(", rpt) is not None
            checks["report_functions_present"] = bool(has_parse and has_compute and has_render)

    # 3) Each Python file in src/text_reports begins with module docstring within first 5 non-empty lines
    checks["module_docstrings_in_src_text_reports"] = False
    doc_ok = True
    count_considered = 0
    for rf in ["src/text_reports/__init__.py", "src/text_reports/report.py", "src/text_reports/cli.py"]:
        ap = abs_paths.get(rf)
        if ap and os.path.isfile(ap):
            count_considered += 1
            txt = read_text(ap)
            if not first_n_nonempty_lines_have_triple_quote(txt, n=5):
                doc_ok = False
    if count_considered == 3 and doc_ok:
        checks["module_docstrings_in_src_text_reports"] = True

    # 4) At least one explicit "raise" in report.py
    checks["report_has_raise"] = False
    if exists_report_py:
        rpt = read_text(abs_paths["src/text_reports/report.py"])
        if rpt is not None and re.search(r"\braise\s+\w+", rpt) is not None:
            checks["report_has_raise"] = True

    # README mentions compile/type and test
    checks["readme_mentions_compile_or_type"] = False
    checks["readme_mentions_test"] = False
    if exists_readme:
        rtxt = read_text(abs_paths["README.md"])
        if rtxt is not None:
            if ("compile" in rtxt.lower()) or ("type" in rtxt.lower()):
                checks["readme_mentions_compile_or_type"] = True
            if "test" in rtxt.lower():
                checks["readme_mentions_test"] = True

    # modified_files.json validity and includes required paths
    checks["modified_files_json_valid"] = False
    checks["modified_files_includes_required_paths"] = False
    modified_valid, modified_list = (False, None)
    if exists_modified:
        modified_valid, modified_list = load_modified_files(abs_paths["modified_files.json"])
        checks["modified_files_json_valid"] = modified_valid
        if modified_valid:
            # Must include at least the relative paths for required files (relative to output/)
            # Build set for quick lookup
            mod_set = set(modified_list)
            includes_all = all((rf in mod_set) for rf in required_files)
            checks["modified_files_includes_required_paths"] = includes_all

    # Auditor logs structure
    def audit_common_checks(audit_abs_path, need_attack_vector=False):
        text = read_text(audit_abs_path)
        # Has "Files to review:" line
        has_line = contains_case_insensitive(text or "", "Files to review:")
        # Will validate at least two modified files listed using helper (requires modified_valid True)
        has_two = False
        if modified_valid:
            line_ok, two_ok = audit_files_list_contains_two_modified(text, modified_list)
            has_line = has_line and line_ok
            has_two = two_ok
        # Has required fields
        has_fields = all(contains_case_insensitive(text or "", fld) for fld in [
            "File and line number", "Category", "Severity"
        ])
        # Fix recommendation exists
        has_fix_rec = contains_case_insensitive(text or "", "Fix recommendation")
        # Attack vector for harden
        has_attack = True
        if need_attack_vector:
            has_attack = (contains_case_insensitive(text or "", "Attack vector")
                          or contains_case_insensitive(text or "", "not applicable"))
        return has_line, has_two, has_fields, has_fix_rec, has_attack

    # Simplify
    checks["audit_round1_simplify_has_files_to_review_line"] = False
    checks["audit_round1_simplify_lists_two_modified_files"] = False
    checks["audit_round1_simplify_has_required_fields"] = False
    checks["audit_round1_simplify_has_fix_recommendation"] = False
    if exists_audit_simplify:
        has_line, has_two, has_fields, has_fix, _ = audit_common_checks(abs_paths["audit/round1_simplify.md"])
        checks["audit_round1_simplify_has_files_to_review_line"] = has_line
        checks["audit_round1_simplify_lists_two_modified_files"] = has_two
        checks["audit_round1_simplify_has_required_fields"] = has_fields
        checks["audit_round1_simplify_has_fix_recommendation"] = has_fix

    # Harden
    checks["audit_round1_harden_has_files_to_review_line"] = False
    checks["audit_round1_harden_lists_two_modified_files"] = False
    checks["audit_round1_harden_has_required_fields"] = False
    checks["audit_round1_harden_has_fix_recommendation"] = False
    checks["audit_round1_harden_has_attack_vector_or_na"] = False
    if exists_audit_harden:
        has_line, has_two, has_fields, has_fix, has_attack = audit_common_checks(
            abs_paths["audit/round1_harden.md"], need_attack_vector=True
        )
        checks["audit_round1_harden_has_files_to_review_line"] = has_line
        checks["audit_round1_harden_lists_two_modified_files"] = has_two
        checks["audit_round1_harden_has_required_fields"] = has_fields
        checks["audit_round1_harden_has_fix_recommendation"] = has_fix
        checks["audit_round1_harden_has_attack_vector_or_na"] = has_attack

    # Spec
    checks["audit_round1_spec_has_files_to_review_line"] = False
    checks["audit_round1_spec_lists_two_modified_files"] = False
    checks["audit_round1_spec_has_required_fields"] = False
    checks["audit_round1_spec_has_fix_recommendation"] = False
    if exists_audit_spec:
        has_line, has_two, has_fields, has_fix, _ = audit_common_checks(abs_paths["audit/round1_spec.md"])
        checks["audit_round1_spec_has_files_to_review_line"] = has_line
        checks["audit_round1_spec_lists_two_modified_files"] = has_two
        checks["audit_round1_spec_has_required_fields"] = has_fields
        checks["audit_round1_spec_has_fix_recommendation"] = has_fix

    # Final hardening summary
    checks["summary_has_heading_hardening_summary"] = False
    checks["summary_has_audit_rounds_completed_field"] = False
    checks["summary_has_valid_exit_reason"] = False
    checks["summary_has_findings_by_round_section"] = False
    checks["summary_has_actions_taken_section"] = False
    checks["summary_has_unresolved_section"] = False
    checks["summary_has_out_of_scope_observations_section"] = False
    checks["summary_has_budget_section_and_leq_30_cap"] = False

    if exists_summary:
        stxt = read_text(abs_paths["report.md"])
        if stxt is not None:
            checks["summary_has_heading_hardening_summary"] = contains_case_insensitive(stxt, "Hardening Summary")
            checks["summary_has_audit_rounds_completed_field"] = contains_case_insensitive(stxt, "Audit rounds completed:")
            checks["summary_has_valid_exit_reason"] = validate_exit_reason(stxt)
            checks["summary_has_findings_by_round_section"] = contains_case_insensitive(stxt, "Findings by round")
            checks["summary_has_actions_taken_section"] = contains_case_insensitive(stxt, "Actions taken")
            checks["summary_has_unresolved_section"] = contains_case_insensitive(stxt, "Unresolved")
            checks["summary_has_out_of_scope_observations_section"] = contains_case_insensitive(stxt, "Out-of-scope observations")
            has_budget = contains_case_insensitive(stxt, "Budget")
            mentions_cap = contains_case_insensitive(stxt, "<=30%")
            checks["summary_has_budget_section_and_leq_30_cap"] = bool(has_budget and mentions_cap)

    # Compute reward: fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Baseline: if output dir missing or empty and no checks passed, reward must be 0.0 (already covered)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()