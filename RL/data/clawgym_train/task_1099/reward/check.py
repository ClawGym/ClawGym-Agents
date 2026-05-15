import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def count_leading_spaces(s):
    return len(s) - len(s.lstrip(" "))

def get_function_body_text(source, func_name):
    # Naive function body extractor based on indentation
    lines = source.splitlines(True)  # keep newlines
    pattern = re.compile(rf'^\s*def\s+{re.escape(func_name)}\s*\(.*\)\s*:', re.MULTILINE)
    for i, line in enumerate(lines):
        if pattern.match(line):
            def_indent = count_leading_spaces(line)
            body_lines = []
            j = i + 1
            while j < len(lines):
                l = lines[j]
                # Always include blank lines/comments as part of body
                if l.strip() == "":
                    body_lines.append(l)
                    j += 1
                    continue
                ind = count_leading_spaces(l)
                # Terminate when we reach a sibling or outer scope def/class at same or lower indent
                if ind <= def_indent and re.match(r'^\s*(def|class)\s+\w+', l):
                    break
                body_lines.append(l)
                j += 1
            return "".join(body_lines)
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths to required artifacts
    bank_py_path = os.path.join(output_dir, "src", "bank.py")
    smoke_py_path = os.path.join(output_dir, "tests", "smoke.py")
    readme_path = os.path.join(output_dir, "README.md")

    checks = {
        # Existence checks
        "has_bank_py": False,
        "has_smoke_py": False,
        "has_readme": False,
        # bank.py content checks
        "bank_has_class_and_invariants_method": False,
        "bank_has_asserts_with_messages_count_ge_3": False,
        "bank_has_debug_only_invariants_section": False,
        "bank_deposit_raises_value_error": False,
        "bank_withdraw_raises_value_error": False,
        "bank_has_postcondition_old_balance_assert": False,
        "bank_transfer_has_conservation_assert": False,
        "bank_avoid_catching_assertionerror": False,
        "bank_no_security_asserts": False,
        # README checks
        "readme_length_ge_800": False,
        "readme_has_keywords": False,
        # smoke test content checks
        "smoke_has_bank_import": False,
        "smoke_has_try_except_valueerror": False,
        "smoke_has_transfer_call": False,
        "smoke_instantiates_bankaccount": False,
    }

    # Existence
    checks["has_bank_py"] = os.path.isfile(bank_py_path)
    checks["has_smoke_py"] = os.path.isfile(smoke_py_path)
    checks["has_readme"] = os.path.isfile(readme_path)

    bank_src = read_text(bank_py_path) if checks["has_bank_py"] else ""
    smoke_src = read_text(smoke_py_path) if checks["has_smoke_py"] else ""
    readme_text = read_text(readme_path) if checks["has_readme"] else ""

    # bank.py: class and invariants method
    if bank_src:
        if "class BankAccount" in bank_src and re.search(r'^\s*def\s+_check_invariants\s*\(', bank_src, re.MULTILINE):
            checks["bank_has_class_and_invariants_method"] = True

        # Assertions with messages (double-quoted)
        assert_with_msg_pattern = re.compile(r'^\s*assert\s+[^#\n]+,\s*"(?:[^"\\]|\\.)+"', re.MULTILINE)
        if len(assert_with_msg_pattern.findall(bank_src)) >= 3:
            checks["bank_has_asserts_with_messages_count_ge_3"] = True

        # Debug-only section
        if "if __debug__:" in bank_src:
            checks["bank_has_debug_only_invariants_section"] = True

        # Function bodies
        deposit_body = get_function_body_text(bank_src, "deposit")
        withdraw_body = get_function_body_text(bank_src, "withdraw")
        transfer_body = get_function_body_text(bank_src, "transfer")

        if deposit_body and "raise ValueError" in deposit_body:
            checks["bank_deposit_raises_value_error"] = True
        if withdraw_body and "raise ValueError" in withdraw_body:
            checks["bank_withdraw_raises_value_error"] = True

        # Postcondition evidence using old_balance
        if re.search(r'\bold_balance\s*=', bank_src) and re.search(r'^\s*assert\s+.*old_balance', bank_src, re.MULTILINE):
            checks["bank_has_postcondition_old_balance_assert"] = True

        # Transfer conservation: assert mentioning conservation or using total_before
        transfer_has_conserve_word = bool(re.search(r'assert.*conserv', transfer_body, re.IGNORECASE | re.DOTALL)) if transfer_body else False
        transfer_has_total_before = False
        if transfer_body:
            if re.search(r'\btotal_before\s*=', transfer_body) and re.search(r'assert\s+.*total_before', transfer_body):
                transfer_has_total_before = True
        if transfer_has_conserve_word or transfer_has_total_before:
            checks["bank_transfer_has_conservation_assert"] = True

        # Anti-pattern avoidance
        checks["bank_avoid_catching_assertionerror"] = ("except AssertionError" not in bank_src)
        # Security asserts like is_admin/token usage
        security_assert_bad = bool(re.search(r'assert\s+.*is_admin', bank_src)) or bool(re.search(r'assert\s+.*token', bank_src))
        checks["bank_no_security_asserts"] = not security_assert_bad

    # README checks
    if readme_text:
        if len(readme_text) >= 800:
            checks["readme_length_ge_800"] = True
        lower = readme_text.lower()
        keywords = ["preconditions", "postconditions", "invariants", "anti-patterns", "design-by-contract", "assertions", "exceptions"]
        if all(k in lower for k in keywords):
            checks["readme_has_keywords"] = True

    # Smoke test checks (static content only)
    if smoke_src:
        # bank import
        if re.search(r'^\s*(from\s+.*bank.*import|import\s+.*bank.*)', smoke_src, re.MULTILINE):
            checks["smoke_has_bank_import"] = True
        # try/except ValueError
        if "try:" in smoke_src and re.search(r'except\s+ValueError\b', smoke_src):
            checks["smoke_has_try_except_valueerror"] = True
        # transfer call
        if re.search(r'\btransfer\s*\(', smoke_src):
            checks["smoke_has_transfer_call"] = True
        # BankAccount instantiation
        if "BankAccount(" in smoke_src:
            checks["smoke_instantiates_bankaccount"] = True

    # Gate reward: if any required artifact missing, reward must be 0.0
    all_required_exist = checks["has_bank_py"] and checks["has_smoke_py"] and checks["has_readme"]

    # Compute reward as fraction of passed checks if all required exist; else 0.0
    scored_keys = list(checks.keys())
    passed = sum(1 for k in scored_keys if checks[k])
    total = len(scored_keys)
    reward = (passed / total) if (total > 0 and all_required_exist) else 0.0
    # Clamp to [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()