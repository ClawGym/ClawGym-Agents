import json
import os
import sys
import xml.etree.ElementTree as ET

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        # Existence checks
        "has_mock_server_file": False,
        "has_tests_file": False,
        "has_report_json_file": False,
        "has_junit_file": False,
        "has_summary_html_file": False,
        "has_contract_file": False,
        "has_perf_file": False,
        "readme_present": False,  # optional; does not affect reward

        # Mock server content checks
        "mock_mentions_users_path": False,
        "mock_mentions_users_id_path": False,
        "mock_mentions_methods": False,
        "mock_mentions_json": False,

        # Tests content checks
        "tests_mentions_users_path": False,
        "tests_mentions_users_id_path": False,
        "tests_mentions_methods": False,
        "tests_reference_openapi": False,
        "tests_negative_present": False,
        "maintainability_terms_present": False,

        # Reports validity checks
        "report_json_valid": False,
        "junit_xml_valid": False,
        "summary_html_contains_sections": False,
        "summary_html_lists_endpoints": False,
        "contract_json_valid": False,
        "perf_json_valid": False,
    }

    # Paths
    mock_server_path = os.path.join(output_dir, "mock_server.py")
    tests_path = os.path.join(output_dir, "tests", "test_api.py")
    report_json_path = os.path.join(output_dir, "reports", "report.json")
    junit_xml_path = os.path.join(output_dir, "reports", "junit.xml")
    summary_html_path = os.path.join(output_dir, "reports", "summary.html")
    contract_json_path = os.path.join(output_dir, "reports", "contract.json")
    perf_json_path = os.path.join(output_dir, "reports", "perf.json")
    readme_path = os.path.join(output_dir, "README.md")

    # Required endpoints list (exact strings)
    required_endpoints = [
        "GET /api/users",
        "POST /api/users",
        "GET /api/users/{id}",
        "PUT /api/users/{id}",
        "DELETE /api/users/{id}",
    ]

    # Existence
    checks["has_mock_server_file"] = os.path.isfile(mock_server_path)
    checks["has_tests_file"] = os.path.isfile(tests_path)
    checks["has_report_json_file"] = os.path.isfile(report_json_path)
    checks["has_junit_file"] = os.path.isfile(junit_xml_path)
    checks["has_summary_html_file"] = os.path.isfile(summary_html_path)
    checks["has_contract_file"] = os.path.isfile(contract_json_path)
    checks["has_perf_file"] = os.path.isfile(perf_json_path)
    checks["readme_present"] = os.path.isfile(readme_path)

    # Mock server content checks
    mock_text = ""
    if checks["has_mock_server_file"]:
        mock_text = read_text(mock_server_path)
        lower_mock = mock_text.lower()
        checks["mock_mentions_users_path"] = "/api/users" in mock_text
        checks["mock_mentions_users_id_path"] = "/api/users/{id}" in mock_text
        methods = ["GET", "POST", "PUT", "DELETE"]
        checks["mock_mentions_methods"] = all(m in mock_text for m in methods)
        # JSON-centric handling evidence
        checks["mock_mentions_json"] = (
            "application/json" in lower_mock
            or "\"users\"" in mock_text
            or "json" in lower_mock
        )

    # Tests content checks
    tests_text = ""
    if checks["has_tests_file"]:
        tests_text = read_text(tests_path)
        lower_tests = tests_text.lower()
        checks["tests_mentions_users_path"] = "/api/users" in tests_text
        checks["tests_mentions_users_id_path"] = "/api/users/{id}" in tests_text
        methods = ["GET", "POST", "PUT", "DELETE"]
        checks["tests_mentions_methods"] = all(m in tests_text for m in methods)
        checks["tests_reference_openapi"] = ("openapi.yaml" in tests_text) or ("input/openapi.yaml" in tests_text)
        # Negative test evidence: look for invalid/missing or explicit non-2xx assertions
        negative_terms = ["invalid", "missing", "non-2xx", "400", "422"]
        has_neg_terms = any(term in lower_tests for term in negative_terms)
        # Also consider explicit assertion of non-2xx or expecting failure
        has_neg_assert = ("assert" in lower_tests and ("400" in lower_tests or "422" in lower_tests or ">= 400" in lower_tests))
        checks["tests_negative_present"] = has_neg_terms or has_neg_assert

    # Maintainability heuristics across code files
    combined_code = (mock_text + "\n" + tests_text).lower()
    maintainability_terms = ["setup", "teardown", "fixture", "contract", "performance", "negative"]
    present_count = sum(1 for t in maintainability_terms if t in combined_code)
    checks["maintainability_terms_present"] = present_count >= 3

    # report.json validity
    if checks["has_report_json_file"]:
        try:
            rep = json.loads(read_text(report_json_path))
            keys_ok = all(k in rep for k in ["total_tests", "passed", "failed", "pass_rate", "endpoints_covered"])
            types_ok = (
                keys_ok and
                isinstance(rep["endpoints_covered"], list) and
                is_number(rep["total_tests"]) and
                is_number(rep["passed"]) and
                is_number(rep["failed"]) and
                is_number(rep["pass_rate"])
            )
            endpoints_ok = False
            if types_ok:
                covered = set(rep["endpoints_covered"])
                endpoints_ok = all(ep in covered for ep in required_endpoints)
            pass_rate_rule_ok = False
            if types_ok:
                if int(rep["failed"]) == 0:
                    pass_rate_rule_ok = float(rep["pass_rate"]) == 100.0 or int(rep["pass_rate"]) == 100
                else:
                    # If there are failures, no strict pass_rate rule; consider okay
                    pass_rate_rule_ok = True
            checks["report_json_valid"] = keys_ok and types_ok and endpoints_ok and pass_rate_rule_ok
        except Exception:
            checks["report_json_valid"] = False

    # junit.xml validity
    if checks["has_junit_file"]:
        try:
            tree = ET.parse(junit_xml_path)
            root = tree.getroot()
            # Must contain testsuite and testcase entries
            has_testsuite = (root.tag == "testsuite") or (root.find(".//testsuite") is not None)
            testcases = root.findall(".//testcase")
            names = [tc.get("name", "") for tc in testcases]
            endpoints_present = all(any(req in name for name in names) for req in required_endpoints)
            checks["junit_xml_valid"] = has_testsuite and len(testcases) > 0 and endpoints_present
        except Exception:
            checks["junit_xml_valid"] = False

    # summary.html checks
    if checks["has_summary_html_file"]:
        html = read_text(summary_html_path)
        sections_ok = all(s in html for s in ["API Test Summary", "Functional Tests", "Performance Summary", "Contract Validation", "Endpoints Covered"])
        endpoints_ok = all(ep in html for ep in required_endpoints)
        checks["summary_html_contains_sections"] = sections_ok
        checks["summary_html_lists_endpoints"] = endpoints_ok

    # contract.json validity
    if checks["has_contract_file"]:
        try:
            cobj = json.loads(read_text(contract_json_path))
            checks["contract_json_valid"] = (isinstance(cobj, dict) and cobj.get("valid") is True and cobj.get("endpoints_validated") == 5)
        except Exception:
            checks["contract_json_valid"] = False

    # perf.json validity
    if checks["has_perf_file"]:
        try:
            pobj = json.loads(read_text(perf_json_path))
            req_keys = ["total_requests", "concurrency", "avg_response_time_ms", "throughput_rps", "error_rate"]
            keys_ok = all(k in pobj for k in req_keys)
            nums_ok = keys_ok and all(is_number(pobj[k]) for k in req_keys)
            totals_ok = keys_ok and (int(pobj["total_requests"]) == 100) and (int(pobj["concurrency"]) == 10)
            checks["perf_json_valid"] = keys_ok and nums_ok and totals_ok
        except Exception:
            checks["perf_json_valid"] = False

    # Determine reward
    required_exist_flags = [
        "has_mock_server_file",
        "has_tests_file",
        "has_report_json_file",
        "has_junit_file",
        "has_summary_html_file",
        "has_contract_file",
        "has_perf_file",
    ]
    all_required_present = all(checks[k] for k in required_exist_flags)

    # Compute score as fraction of passed checks (excluding optional readme_present)
    score_checks_keys = [k for k in checks.keys() if k != "readme_present"]
    passed = sum(1 for k in score_checks_keys if checks[k])
    total = len(score_checks_keys)

    if not all_required_present:
        reward = 0.0
    else:
        reward = passed / total if total > 0 else 0.0

    # Emit JSON with "reward" first
    output = {"reward": float(round(reward, 6))}
    output.update(checks)
    print(json.dumps(output))

if __name__ == "__main__":
    main()