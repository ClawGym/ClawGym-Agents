import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

def is_int_but_not_bool(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)

def load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def serialize_body(body: Any) -> str:
    # Serialize body (dict -> JSON string; others -> str)
    if isinstance(body, (dict, list)):
        try:
            return json.dumps(body, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(body)
    return str(body)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False; set True only after positive verification)
    checks: Dict[str, bool] = {
        "results_exists": False,
        "results_valid_json_array": False,
        "results_coverage_complete": False,
        "results_no_extras": False,
        "results_schema_valid": False,
        "statuses_match_and_passed": False,
        "header_echo_verified": False,              # applicable only if headers present in input
        "json_body_echo_verified": False,           # applicable only if POST/PUT with JSON body present
        "report_exists": False,
        "report_has_counts": False,
        "report_has_slowest": False,
        "report_has_per_endpoint_line": False,
        "report_has_failure_root_cause_if_needed": False
    }

    # Load input endpoints (reference only; no direct reward for reading)
    input_endpoints_path = os.path.join(input_dir, "endpoints.json")
    try:
        endpoints: List[Dict[str, Any]] = load_json_file(input_endpoints_path)
        if not isinstance(endpoints, list):
            endpoints = []
    except Exception:
        endpoints = []

    # Expected mapping and sets from input
    expected_pairs: List[Tuple[str, str]] = []
    url_method_to_expected: Dict[Tuple[str, str], Dict[str, Any]] = {}
    header_bearing_expected_pairs: List[Tuple[str, str, Dict[str, str]]] = []
    json_body_expected_pairs: List[Tuple[str, str, Dict[str, Any]]] = []

    for ep in endpoints:
        url = ep.get("url")
        method = (ep.get("method") or "GET").upper()
        if isinstance(url, str) and isinstance(method, str):
            expected_pairs.append((url, method))
            url_method_to_expected[(url, method)] = ep
            # headers applicability
            headers = ep.get("headers")
            if isinstance(headers, dict) and len(headers) > 0:
                header_bearing_expected_pairs.append((url, method, headers))
            # json body applicability (POST/PUT with body object)
            body = ep.get("body")
            if method in ("POST", "PUT") and isinstance(body, dict):
                json_body_expected_pairs.append((url, method, body))

    expected_set = set(expected_pairs)

    # Load outputs
    results_path = os.path.join(output_dir, "results.json")
    report_path = os.path.join(output_dir, "report.md")

    results: Any = None
    if os.path.isfile(results_path):
        checks["results_exists"] = True
        try:
            results = load_json_file(results_path)
            if isinstance(results, list):
                checks["results_valid_json_array"] = True
            else:
                results = None
        except Exception:
            results = None

    # Schema and coverage checks
    results_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    schema_ok = True
    coverage_ok = False
    no_extras_ok = False
    statuses_ok = True

    if isinstance(results, list):
        # Map results by (url, method)
        duplicates_found = False
        for item in results:
            if not isinstance(item, dict):
                schema_ok = False
                continue

            # Allowed keys and required keys
            required_keys = {"url", "method", "expected_status", "status_code", "response_time_ms", "passed", "body"}
            allowed_keys = required_keys.union({"notes"})
            item_keys = set(item.keys())

            # Exactly required keys, with optional 'notes' allowed, nothing else
            if not (item_keys == required_keys or item_keys == allowed_keys):
                schema_ok = False

            # Type checks
            url = item.get("url")
            method = item.get("method")
            expected_status = item.get("expected_status")
            status_code = item.get("status_code")
            response_time_ms = item.get("response_time_ms")
            passed = item.get("passed")
            body = item.get("body")
            notes = item.get("notes") if "notes" in item else None

            if not isinstance(url, str):
                schema_ok = False
            if not isinstance(method, str) or method != method.upper():
                schema_ok = False
            if not is_int_but_not_bool(expected_status):
                schema_ok = False
            if not is_int_but_not_bool(status_code):
                schema_ok = False
            if not is_int_but_not_bool(response_time_ms):
                schema_ok = False
            if not isinstance(passed, bool):
                schema_ok = False
            if not (isinstance(body, dict) or isinstance(body, str)):
                schema_ok = False
            if "notes" in item and not isinstance(notes, str):
                schema_ok = False

            # Build map and detect duplicates
            if isinstance(url, str) and isinstance(method, str):
                key = (url, method)
                if key in results_by_key:
                    duplicates_found = True
                else:
                    results_by_key[key] = item

        # Coverage: every input endpoint must be present exactly once
        if not duplicates_found and all(k in results_by_key for k in expected_set) and len(results_by_key) == len(expected_set):
            coverage_ok = True
        # Extras: no result entries outside input list
        if not duplicates_found and set(results_by_key.keys()).issubset(expected_set) and len(results_by_key) == len(expected_set):
            no_extras_ok = True

        # Statuses and 'passed' must align with expected
        for (url, method), item in results_by_key.items():
            expected = url_method_to_expected.get((url, method), {})
            exp_status = expected.get("expected_status")
            if not is_int_but_not_bool(exp_status):
                statuses_ok = False
                continue
            sc = item.get("status_code")
            p = item.get("passed")
            if not (sc == exp_status and p is True):
                statuses_ok = False

    checks["results_schema_valid"] = bool(schema_ok and isinstance(results, list))
    checks["results_coverage_complete"] = coverage_ok
    checks["results_no_extras"] = no_extras_ok
    checks["statuses_match_and_passed"] = statuses_ok

    # Header echo verification (applicable only if headers present in input)
    header_applicable = len(header_bearing_expected_pairs) > 0
    header_verified = False
    if isinstance(results, list) and header_applicable:
        for (url, method, headers) in header_bearing_expected_pairs:
            res_item = results_by_key.get((url, method))
            if not res_item:
                continue
            body = res_item.get("body")
            body_s = serialize_body(body)
            # search for any provided header value in serialized body
            for hv in headers.values():
                try:
                    hv_str = str(hv)
                    if hv_str and hv_str in body_s:
                        header_verified = True
                        break
                except Exception:
                    continue
            if header_verified:
                break
    checks["header_echo_verified"] = header_verified

    # JSON body echo verification (applicable only if POST/PUT with JSON body exists in input)
    json_echo_applicable = len(json_body_expected_pairs) > 0
    json_echo_verified = False
    if isinstance(results, list) and json_echo_applicable:
        for (url, method, body_obj) in json_body_expected_pairs:
            res_item = results_by_key.get((url, method))
            if not res_item:
                continue
            resp_body = res_item.get("body")
            resp_s = serialize_body(resp_body)
            sent_json_min = json.dumps(body_obj, separators=(",", ":"), sort_keys=True)
            resp_json_min = resp_s
            # Substring match of minified JSON
            match = sent_json_min in resp_json_min
            # Fallback: check all key-value pairs present in serialized response
            if not match and isinstance(resp_body, dict):
                all_kv_present = True
                for k, v in body_obj.items():
                    kv_fragment = json.dumps({k: v}, separators=(",", ":"), sort_keys=True)[1:-1]  # '"k":value' fragment
                    if kv_fragment not in resp_json_min:
                        all_kv_present = False
                        break
                match = all_kv_present
            if match:
                json_echo_verified = True
                break
    checks["json_body_echo_verified"] = json_echo_verified

    # Report checks
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_txt = f.read()
        except Exception:
            report_txt = ""
    else:
        report_txt = ""

    if checks["report_exists"]:
        # Counts presence
        if ("Total" in report_txt) and ("Passed" in report_txt) and ("Failed" in report_txt):
            checks["report_has_counts"] = True

        # Slowest line with "<number> ms"
        if re.search(r"Slowest.*?\b(\d+)\s*ms\b", report_txt, flags=re.IGNORECASE | re.DOTALL):
            checks["report_has_slowest"] = True

        # Per-endpoint line: at least one line with URL + METHOD + both expected and actual statuses numbers
        per_line_ok = False
        lines = report_txt.splitlines()
        http_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        for (url, method) in expected_set:
            exp = url_method_to_expected.get((url, method), {}).get("expected_status")
            actual = None
            if (url, method) in results_by_key:
                actual = results_by_key[(url, method)].get("status_code")
            for ln in lines:
                if url in ln and method in ln:
                    has_exp = (is_int_but_not_bool(exp) and str(exp) in ln) or ("expected" in ln.lower())
                    has_act = (is_int_but_not_bool(actual) and str(actual) in ln) or ("status" in ln.lower())
                    if has_exp and has_act:
                        per_line_ok = True
                        break
            if per_line_ok:
                break
        checks["report_has_per_endpoint_line"] = per_line_ok

        # Failure root-cause note if there are failures in results
        any_failures = False
        if isinstance(results, list):
            any_failures = any((not bool(item.get("passed"))) for item in results if isinstance(item, dict) and "passed" in item)
        if any_failures:
            lowered = report_txt.lower()
            # Look for typical root-cause keywords
            keywords = [
                "header mismatch", "header", "redirect", "json", "ssl", "timeout",
                "connection", "parse", "mismatch", "unexpected", "root-cause", "cause"
            ]
            if any(kw in lowered for kw in keywords):
                checks["report_has_failure_root_cause_if_needed"] = True
        else:
            # Not applicable; keep False but will be excluded from scoring
            pass

    # Determine applicable checks for scoring
    applicable_checks = []
    for k in checks.keys():
        applicable = True
        if k == "header_echo_verified" and not header_applicable:
            applicable = False
        if k == "json_body_echo_verified" and not json_echo_applicable:
            applicable = False
        if k == "report_has_failure_root_cause_if_needed":
            # Only applicable if failures exist in results.json
            any_failures = False
            if isinstance(results, list):
                any_failures = any((not bool(item.get("passed"))) for item in results if isinstance(item, dict) and "passed" in item)
            applicable = any_failures
        applicable_checks.append((k, applicable))

    # Enforce no-op baseline: if required artifacts missing, reward must be 0.0
    required_present = checks["results_exists"] and checks["report_exists"]

    # Compute reward as fraction of passed applicable checks
    passed = 0
    total_applicable = 0
    for key, is_app in applicable_checks:
        if is_app:
            total_applicable += 1
            if checks[key]:
                passed += 1

    reward = 0.0
    if required_present and total_applicable > 0:
        reward = passed / total_applicable
        # Clamp to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0
    else:
        reward = 0.0

    # Print exactly one JSON object as last non-empty line
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()