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

def count_occurrences(text, token):
    if text is None:
        return 0
    return text.count(token)

def exists_and_nonempty(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0

def find_function_span_lines(text, func_name):
    """
    Return the number of lines from 'def <func_name>(' to the line before the next def/class or EOF.
    If not found, return None.
    """
    if text is None:
        return None
    lines = text.splitlines()
    start_idx = None
    func_def_pattern = re.compile(r"^\s*def\s+" + re.escape(func_name) + r"\s*\(")
    next_def_or_class_pattern = re.compile(r"^\s*(def|class)\s+\w+\s*(\(|:)")
    for i, line in enumerate(lines):
        if func_def_pattern.search(line):
            start_idx = i
            break
    if start_idx is None:
        return None
    # find next def/class after start
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if next_def_or_class_pattern.search(lines[j]):
            end_idx = j
            break
    # number of lines in span (inclusive of def line up to line before next block)
    return end_idx - start_idx

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    errors_path = os.path.join(output_dir, "src", "errors.py")
    service_path = os.path.join(output_dir, "src", "service.py")
    repository_path = os.path.join(output_dir, "src", "repository.py")
    handler_path = os.path.join(output_dir, "src", "handler.py")
    tests_path = os.path.join(output_dir, "tests", "test_service.py")
    readme_path = os.path.join(output_dir, "README.md")

    checks = {
        "file_errors_exists": False,
        "file_service_exists": False,
        "file_repository_exists": False,
        "file_handler_exists": False,
        "file_tests_exists": False,
        "file_readme_exists": False,
        "errors_hierarchy_defined": False,
        "service_constants_defined": False,
        "service_constants_used_twice": False,
        "service_has_function": False,
        "service_calc_func_size_ok": False,
        "repository_has_load_prices": False,
        "repository_has_get_price": False,
        "repository_has_default_path_string": False,
        "handler_has_handle_cli": False,
        "handler_uses_argparse": False,
        "handler_no_todo": False,
        "tests_use_unittest": False,
        "tests_cover_test_threshold_boundary": False,
        "tests_cover_test_vip_extra": False,
        "tests_cover_test_discount_cap": False,
        "tests_cover_test_unknown_product": False,
        "tests_cover_test_invalid_order": False,
        "readme_has_architecture": False,
        "readme_has_error_handling": False,
        "readme_has_tradeoffs": False,
        "readme_has_how_to_run": False,
    }

    # Existence checks
    if exists_and_nonempty(errors_path):
        checks["file_errors_exists"] = True
    if exists_and_nonempty(service_path):
        checks["file_service_exists"] = True
    if exists_and_nonempty(repository_path):
        checks["file_repository_exists"] = True
    if exists_and_nonempty(handler_path):
        checks["file_handler_exists"] = True
    if exists_and_nonempty(tests_path):
        checks["file_tests_exists"] = True
    if exists_and_nonempty(readme_path):
        checks["file_readme_exists"] = True

    # Load contents if exist
    errors_text = read_text(errors_path) if checks["file_errors_exists"] else None
    service_text = read_text(service_path) if checks["file_service_exists"] else None
    repository_text = read_text(repository_path) if checks["file_repository_exists"] else None
    handler_text = read_text(handler_path) if checks["file_handler_exists"] else None
    tests_text = read_text(tests_path) if checks["file_tests_exists"] else None
    readme_text = read_text(readme_path) if checks["file_readme_exists"] else None

    # 2) errors.py hierarchy
    if errors_text:
        dom = re.search(r"class\s+DomainError\s*\(\s*Exception\s*\)\s*:", errors_text)
        val = re.search(r"class\s+ValidationError\s*\(\s*DomainError\s*\)\s*:", errors_text)
        nf = re.search(r"class\s+NotFoundError\s*\(\s*DomainError\s*\)\s*:", errors_text)
        if dom and val and nf:
            checks["errors_hierarchy_defined"] = True

    # 3) service.py constants and function size
    constants = ["ORDER_DISCOUNT_THRESHOLD", "BASE_DISCOUNT_RATE", "VIP_EXTRA_RATE", "MAX_DISCOUNT"]
    if service_text:
        # constants defined: appear at least once
        if all(const in service_text for const in constants):
            checks["service_constants_defined"] = True
        # constants used at least twice
        if all(service_text.count(const) >= 2 for const in constants):
            checks["service_constants_used_twice"] = True
        # function present
        if "def calculate_discount(" in service_text:
            checks["service_has_function"] = True
            span = find_function_span_lines(service_text, "calculate_discount")
            if span is not None and span <= 35:
                checks["service_calc_func_size_ok"] = True

    # 4) repository.py helpers and default path string
    if repository_text:
        if "def load_prices(" in repository_text:
            checks["repository_has_load_prices"] = True
        if "def get_price(" in repository_text:
            checks["repository_has_get_price"] = True
        if "input/products.csv" in repository_text:
            checks["repository_has_default_path_string"] = True

    # 5) handler.py CLI entry, argparse use, no TODO
    if handler_text:
        if "def handle_cli(" in handler_text:
            checks["handler_has_handle_cli"] = True
        # argparse usage
        if "import argparse" in handler_text and ("argparse.ArgumentParser" in handler_text or "ArgumentParser(" in handler_text):
            checks["handler_uses_argparse"] = True
        if "TODO" not in handler_text:
            checks["handler_no_todo"] = True

    # 6) tests content
    if tests_text:
        if "import unittest" in tests_text:
            checks["tests_use_unittest"] = True
        # required test names substrings
        if "test_threshold_boundary" in tests_text:
            checks["tests_cover_test_threshold_boundary"] = True
        if "test_vip_extra" in tests_text:
            checks["tests_cover_test_vip_extra"] = True
        if "test_discount_cap" in tests_text:
            checks["tests_cover_test_discount_cap"] = True
        if "test_unknown_product" in tests_text:
            checks["tests_cover_test_unknown_product"] = True
        if "test_invalid_order" in tests_text:
            checks["tests_cover_test_invalid_order"] = True

    # 7) README sections
    if readme_text:
        if "Architecture" in readme_text:
            checks["readme_has_architecture"] = True
        if "Error Handling" in readme_text:
            checks["readme_has_error_handling"] = True
        if "Trade-offs" in readme_text or "Tradeoffs" in readme_text:
            checks["readme_has_tradeoffs"] = True
        if "How to run" in readme_text or "How to Run" in readme_text:
            checks["readme_has_how_to_run"] = True

    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()