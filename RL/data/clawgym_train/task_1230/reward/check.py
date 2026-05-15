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

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_class_block(src, class_name):
    # Returns the text block of a class definition up to the next class or end
    pattern = re.compile(rf"class\s+{re.escape(class_name)}\s*\(.*?\)\s*:\s*", re.MULTILINE)
    m = pattern.search(src)
    if not m:
        return None
    start = m.end()
    # Find next class
    next_class = re.compile(r"^\s*class\s+\w+\s*\(.*?\)\s*:\s*", re.MULTILINE).search(src, start)
    end = next_class.start() if next_class else len(src)
    return src[start:end]

def has_any(s, needles):
    s_low = s.lower()
    return any(n.lower() in s_low for n in needles)

def check_error_samples_structure(obj):
    # Accept: list of 2 objects; or dict with key 'errors' or 'samples' (list of 2); or dict with exactly 2 objects
    items = None
    if isinstance(obj, list):
        items = obj
    elif isinstance(obj, dict):
        if "errors" in obj and isinstance(obj["errors"], list):
            items = obj["errors"]
        elif "samples" in obj and isinstance(obj["samples"], list):
            items = obj["samples"]
        else:
            # take values if exactly 2
            if len(obj) == 2:
                items = list(obj.values())
    if not isinstance(items, list) or len(items) != 2:
        return False, None
    # Ensure each has error envelope keys
    for it in items:
        if not isinstance(it, dict):
            return False, None
        err = it.get("error")
        if not isinstance(err, dict):
            return False, None
        if not isinstance(err.get("code"), str):
            return False, None
        if not isinstance(err.get("message"), str):
            return False, None
        if "details" not in err:
            return False, None
        if not isinstance(err.get("requestId"), str):
            return False, None
    return True, items

def detect_codes_in_samples(items):
    # Determine presence of a 404 Not Found sample and a 422 Validation sample
    has_404 = False
    has_422 = False
    for it in items:
        err = it.get("error", {})
        code = err.get("code")
        status = err.get("status") or err.get("statusCode") or err.get("httpStatus")
        # Check code text
        if isinstance(code, str):
            up = code.upper()
            if "NOT_FOUND" in up:
                has_404 = True
            if "VALIDATION" in up:
                has_422 = True
        # Check status numeric
        try:
            if status is not None:
                sval = int(status)
                if sval == 404:
                    has_404 = True
                if sval == 422:
                    has_422 = True
        except Exception:
            pass
    return has_404, has_422

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_app_py": False,
        "has_errors_py": False,
        "has_retry_py": False,
        "has_status_mapping_json": False,
        "has_error_samples_json": False,
        "has_readme_md": False,
        "all_required_files_present": False,

        "errors_base_class": False,
        "errors_not_found_class": False,
        "errors_not_found_status_404": False,
        "errors_validation_class": False,
        "errors_validation_status_422": False,
        "errors_conflict_or_rate_limit_class": False,
        "errors_conflict_or_rate_limit_status": False,

        "retry_has_with_retry": False,
        "retry_has_random_and_sleep": False,
        "retry_has_is_retryable": False,
        "retry_retryable_statuses_present": False,
        "retry_retryable_connection_reset_present": False,
        "circuit_breaker_class_present": False,
        "circuit_breaker_states_present": False,
        "circuit_breaker_methods_present": False,

        "status_mapping_valid_and_contains_keys": False,

        "error_samples_two_entries": False,
        "error_samples_envelope_keys_present": False,
        "error_samples_have_404_and_422_codes": False,

        "no_bare_except": False,
        "readme_has_required_phrases": False,

        "app_logging_has_request_id": False,
        "app_has_error_envelope_keys": False,
        "app_uses_with_retry": False,
        "app_mentions_circuit_breaker": False,
    }

    # Paths
    app_py_path = os.path.join(output_dir, "app.py")
    errors_py_path = os.path.join(output_dir, "errors.py")
    retry_py_path = os.path.join(output_dir, "retry.py")
    status_mapping_path = os.path.join(output_dir, "status_mapping.json")
    error_samples_path = os.path.join(output_dir, "error_samples.json")
    readme_path = os.path.join(output_dir, "README.md")

    # File existence
    if os.path.isfile(app_py_path):
        checks["has_app_py"] = True
    if os.path.isfile(errors_py_path):
        checks["has_errors_py"] = True
    if os.path.isfile(retry_py_path):
        checks["has_retry_py"] = True
    if os.path.isfile(status_mapping_path):
        checks["has_status_mapping_json"] = True
    if os.path.isfile(error_samples_path):
        checks["has_error_samples_json"] = True
    if os.path.isfile(readme_path):
        checks["has_readme_md"] = True

    checks["all_required_files_present"] = all([
        checks["has_app_py"],
        checks["has_errors_py"],
        checks["has_retry_py"],
        checks["has_status_mapping_json"],
        checks["has_error_samples_json"],
        checks["has_readme_md"],
    ])

    # errors.py content checks
    errors_src = read_text(errors_py_path) if checks["has_errors_py"] else None
    if errors_src:
        if re.search(r"class\s+AppError\s*\(\s*Exception\s*\)\s*:", errors_src):
            checks["errors_base_class"] = True

        # NotFoundError presence and 404 status mapping
        if re.search(r"class\s+NotFoundError\s*\(\s*AppError\s*\)\s*:", errors_src):
            checks["errors_not_found_class"] = True
            block = find_class_block(errors_src, "NotFoundError")
            if block and re.search(r"\bstatus_code\b\s*=\s*404\b", block):
                checks["errors_not_found_status_404"] = True
            else:
                # fallback: any 404 mentioned in class block
                if block and "404" in block:
                    checks["errors_not_found_status_404"] = True

        # ValidationError presence and 422 status
        if re.search(r"class\s+ValidationError\s*\(\s*AppError\s*\)\s*:", errors_src):
            checks["errors_validation_class"] = True
            block = find_class_block(errors_src, "ValidationError")
            if block and re.search(r"\bstatus_code\b\s*=\s*422\b", block):
                checks["errors_validation_status_422"] = True
            else:
                if block and "422" in block:
                    checks["errors_validation_status_422"] = True

        # Conflict (409) or RateLimit (429) subclass
        conflict_m = re.search(r"class\s+(ConflictError|Duplicate\w*Error)\s*\(\s*AppError\s*\)\s*:", errors_src)
        rate_m = re.search(r"class\s+RateLimitError\s*\(\s*AppError\s*\)\s*:", errors_src)
        if conflict_m or rate_m:
            checks["errors_conflict_or_rate_limit_class"] = True
            block_name = None
            code_num = None
            if conflict_m:
                block_name = conflict_m.group(1) if conflict_m.group(1).endswith("Error") else "ConflictError"
                code_num = "409"
            elif rate_m:
                block_name = "RateLimitError"
                code_num = "429"
            blk = find_class_block(errors_src, block_name) if block_name else None
            if blk and code_num and code_num in blk:
                checks["errors_conflict_or_rate_limit_status"] = True
            else:
                # fallback: whole file contains the code number
                if code_num and code_num in errors_src:
                    checks["errors_conflict_or_rate_limit_status"] = True

    # retry.py content checks
    retry_src = read_text(retry_py_path) if checks["has_retry_py"] else None
    if retry_src:
        if re.search(r"def\s+with_retry\s*\(", retry_src):
            checks["retry_has_with_retry"] = True
        if ("random" in retry_src) and ("sleep(" in retry_src or "time.sleep" in retry_src):
            checks["retry_has_random_and_sleep"] = True
        if re.search(r"def\s+is_retryable\s*\(", retry_src):
            checks["retry_has_is_retryable"] = True
        # statuses
        statuses = ["408", "429", "500", "502", "503", "504"]
        count_status = sum(1 for s in statuses if s in retry_src)
        if count_status >= 4:
            checks["retry_retryable_statuses_present"] = True
        if ("ECONNRESET" in retry_src) or ("ConnectionResetError" in retry_src) or ("connection reset" in retry_src.lower()):
            checks["retry_retryable_connection_reset_present"] = True
        # CircuitBreaker
        if re.search(r"class\s+CircuitBreaker\s*(\(|:)", retry_src):
            checks["circuit_breaker_class_present"] = True
            if all(x in retry_src for x in ["'CLOSED'", "'OPEN'", "'HALF_OPEN'"]):
                checks["circuit_breaker_states_present"] = True
            # Methods: call, onSuccess/on_success, onFailure/on_failure
            has_call = re.search(r"def\s+call\s*\(", retry_src, flags=re.IGNORECASE) is not None
            has_on_success = re.search(r"def\s+on[_]?success\s*\(", retry_src, flags=re.IGNORECASE) is not None
            has_on_failure = re.search(r"def\s+on[_]?failure\s*\(", retry_src, flags=re.IGNORECASE) is not None
            if has_call and has_on_success and has_on_failure:
                checks["circuit_breaker_methods_present"] = True

    # status_mapping.json checks
    status_obj = load_json(status_mapping_path) if checks["has_status_mapping_json"] else None
    if status_obj is not None and isinstance(status_obj, (dict,)):
        needed = ["400", "401", "403", "404", "409", "422", "429", "500", "502", "503"]
        keys = set(str(k) for k in status_obj.keys())
        if all(code in keys for code in needed):
            # Names should be non-empty strings
            names_ok = True
            for code in needed:
                val = status_obj.get(code) if code in status_obj else status_obj.get(int(code), None)
                if not isinstance(val, str) or not val.strip():
                    names_ok = False
                    break
            if names_ok:
                checks["status_mapping_valid_and_contains_keys"] = True

    # error_samples.json checks
    samples_obj = load_json(error_samples_path) if checks["has_error_samples_json"] else None
    if samples_obj is not None:
        ok, items = check_error_samples_structure(samples_obj)
        if ok:
            checks["error_samples_two_entries"] = True
            # envelope keys already validated in function -> reuse
            checks["error_samples_envelope_keys_present"] = True
            has_404, has_422 = detect_codes_in_samples(items)
            if has_404 and has_422:
                checks["error_samples_have_404_and_422_codes"] = True

    # No bare except across all .py files in output/
    no_bare = True
    if os.path.isdir(output_dir):
        for root, dirs, files in os.walk(output_dir):
            for fn in files:
                if fn.endswith(".py"):
                    p = os.path.join(root, fn)
                    txt = read_text(p) or ""
                    if "except:" in txt:
                        no_bare = False
                        break
            if not no_bare:
                break
    checks["no_bare_except"] = no_bare

    # README required phrases
    readme_txt = read_text(readme_path) if checks["has_readme_md"] else None
    if readme_txt:
        low = readme_txt.lower()
        if ("operational errors" in low and
            "programmer errors" in low and
            "exponential backoff" in low and
            "circuit breaker" in low and
            ("correlation id" in low or "requestid" in low)):
            checks["readme_has_required_phrases"] = True

    # app.py checks for logging and envelope and retry usage
    app_src = read_text(app_py_path) if checks["has_app_py"] else None
    if app_src:
        # Structured logging + correlation id
        if (("requestId" in app_src or "request_id" in app_src) and ("logging" in app_src or "logger" in app_src)):
            checks["app_logging_has_request_id"] = True
        # Error envelope keys in code paths
        if all(k in app_src for k in ["code", "message", "details", "requestId"]):
            checks["app_has_error_envelope_keys"] = True
        # Retry usage
        if "with_retry(" in app_src:
            checks["app_uses_with_retry"] = True
        # Circuit breaker mention (optional)
        if "CircuitBreaker" in app_src:
            checks["app_mentions_circuit_breaker"] = True

    # Reward calculation
    # If required files missing, enforce reward = 0.0
    # Otherwise, reward is fraction of passed checks.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    if not checks["all_required_files_present"]:
        reward = 0.0
    else:
        # Exclude no-op required files check from denominator to avoid double-penalizing
        denom_keys = list(checks.keys())
        # We keep all checks in denominator; required-files-present is part of it
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()