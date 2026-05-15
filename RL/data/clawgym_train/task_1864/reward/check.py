import json
import os
import sys
import re

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def is_nonempty_text(s):
    return isinstance(s, str) and len(s.strip()) > 0

def endswith_any(path_str, candidates):
    if not isinstance(path_str, str):
        return False
    for c in candidates:
        if path_str.endswith(c):
            return True
    return False

def normalize_bool(b):
    return bool(b)

def extract_issues_and_summary(obj):
    # Returns (issues_list, summary_dict or None)
    if isinstance(obj, list):
        issues = [x for x in obj if isinstance(x, dict)]
        # Try to find a summary object embedded as an element with key 'summary'
        summary = None
        for x in obj:
            if isinstance(x, dict) and "summary" in x and isinstance(x["summary"], dict):
                summary = x["summary"]
                break
        return issues, summary
    if isinstance(obj, dict):
        # Prefer "issues", fallback to "findings" or "items"
        issues = None
        for key in ("issues", "findings", "items"):
            if key in obj and isinstance(obj[key], list):
                issues = [x for x in obj[key] if isinstance(x, dict)]
                break
        # If no explicit list, but looks like a mapping of issues by id, ignore as invalid
        summary = obj.get("summary") if isinstance(obj.get("summary"), dict) else None
        return issues, summary
    return None, None

def has_required_issue_fields(issues):
    """
    Each issue must include non-empty fields:
    severity, category, check_id, message, file, suggestion.
    'line' may be missing or empty.
    Severity must be one of: critical, warning, info.
    Category must be one of: security, performance, style, tests.
    """
    valid_sev = {"critical", "warning", "info"}
    valid_cat = {"security", "performance", "style", "tests"}
    if not isinstance(issues, list):
        return False
    for it in issues:
        if not isinstance(it, dict):
            return False
        # Required keys
        for k in ("severity", "category", "check_id", "message", "file", "suggestion"):
            if k not in it:
                return False
            v = it[k]
            if not isinstance(v, str) or len(v.strip()) == 0:
                return False
        # Enum checks
        if it["severity"].lower() not in valid_sev:
            return False
        if it["category"].lower() not in valid_cat:
            return False
        # 'line' allowed to be missing or empty; if present, any type is fine
    return True

def summary_has_severity_counts(summary):
    """
    Summary must include integer counts for critical, warning, info.
    Accept either directly as keys or under summary['by_severity'].
    """
    if not isinstance(summary, dict):
        return False
    # Direct keys
    direct = all(k in summary and isinstance(summary[k], int) for k in ("critical", "warning", "info"))
    bysev = isinstance(summary.get("by_severity"), dict) and all(
        k in summary["by_severity"] and isinstance(summary["by_severity"][k], int)
        for k in ("critical", "warning", "info")
    )
    return direct or bysev

def summary_has_category_counts(summary):
    """
    Summary must include integer counts for categories: security, performance, style, tests.
    Accept either directly or under summary['by_category'].
    """
    if not isinstance(summary, dict):
        return False
    keys = ("security", "performance", "style", "tests")
    direct = all(k in summary and isinstance(summary[k], int) for k in keys)
    bycat = isinstance(summary.get("by_category"), dict) and all(
        k in summary["by_category"] and isinstance(summary["by_category"][k], int)
        for k in keys
    )
    return direct or bycat

def find_matching_issue(issues, check_id, category, severity, file_exact=None, file_any=None):
    """
    Return True if an issue is found that matches the given constraints and has non-empty suggestion.
    Uses case-insensitive matching for severity/category/ID, and endswith for file path matching.
    """
    if not isinstance(issues, list):
        return False
    for it in issues:
        if not isinstance(it, dict):
            continue
        sev = str(it.get("severity", "")).lower()
        cat = str(it.get("category", "")).lower()
        cid = str(it.get("check_id", ""))
        if sev != str(severity).lower():
            continue
        if cat != str(category).lower():
            continue
        if cid != check_id:
            continue
        file_val = it.get("file", "")
        if file_exact is not None:
            if not endswith_any(file_val, [file_exact]):
                continue
        if file_any is not None:
            if not endswith_any(file_val, file_any):
                continue
        # Suggestion must be present and non-empty
        sugg = it.get("suggestion", "")
        if not isinstance(sugg, str) or len(sugg.strip()) == 0:
            continue
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Checks dictionary
    checks = {}

    # Paths
    json_path = os.path.join(output_dir, "review-checklist.json")
    md_path = os.path.join(output_dir, "review-checklist.md")
    pr_path = os.path.join(output_dir, "pr-template-thorough.md")

    # Initialize critical existence checks
    json_exists = os.path.isfile(json_path)
    md_exists = os.path.isfile(md_path)
    pr_exists = os.path.isfile(pr_path)

    checks["json_exists"] = json_exists
    checks["md_exists"] = md_exists
    checks["pr_exists"] = pr_exists

    # No-op baseline: if output dir missing or no required files, reward will be 0.0
    issues = None
    summary = None
    json_valid = False
    checks["json_valid"] = False
    checks["json_has_issues_array"] = False
    checks["issues_fields_ok"] = False
    checks["json_has_summary"] = False
    checks["summary_severity_counts"] = False
    checks["summary_category_counts"] = False

    if json_exists:
        try:
            with open(json_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            json_valid = True
            checks["json_valid"] = True
            issues, summary = extract_issues_and_summary(data)
            if isinstance(issues, list):
                checks["json_has_issues_array"] = True
                checks["issues_fields_ok"] = has_required_issue_fields(issues)
            if isinstance(summary, dict):
                checks["json_has_summary"] = True
                checks["summary_severity_counts"] = summary_has_severity_counts(summary)
                checks["summary_category_counts"] = summary_has_category_counts(summary)
        except Exception:
            json_valid = False
            # Keep checks as False

    # Required findings checks (initialized False, set True only if found)
    required_checks = {
        "has_SEC_001_auth": False,
        "has_SEC_002_db": False,
        "has_SEC_003_auth_or_frontend": False,
        "has_SEC_004_auth_or_frontend": False,
        "has_SEC_005_auth": False,
        "has_SEC_006_auth": False,
        "has_PERF_001_db": False,
        "has_PERF_003_db": False,
        "has_STYLE_001_utils": False,
        "has_STYLE_002_longline": False,
    }
    checks.update(required_checks)

    if isinstance(issues, list):
        checks["has_SEC_001_auth"] = find_matching_issue(
            issues, "SEC-001", "security", "critical", file_exact="app/auth.py"
        )
        checks["has_SEC_002_db"] = find_matching_issue(
            issues, "SEC-002", "security", "critical", file_exact="app/db.py"
        )
        checks["has_SEC_003_auth_or_frontend"] = find_matching_issue(
            issues, "SEC-003", "security", "warning", file_any=["app/auth.py", "frontend/app.js"]
        )
        checks["has_SEC_004_auth_or_frontend"] = find_matching_issue(
            issues, "SEC-004", "security", "warning", file_any=["app/auth.py", "frontend/app.js"]
        )
        checks["has_SEC_005_auth"] = find_matching_issue(
            issues, "SEC-005", "security", "critical", file_exact="app/auth.py"
        )
        checks["has_SEC_006_auth"] = find_matching_issue(
            issues, "SEC-006", "security", "critical", file_exact="app/auth.py"
        )
        checks["has_PERF_001_db"] = find_matching_issue(
            issues, "PERF-001", "performance", "critical", file_exact="app/db.py"
        )
        checks["has_PERF_003_db"] = find_matching_issue(
            issues, "PERF-003", "performance", "info", file_exact="app/db.py"
        )
        checks["has_STYLE_001_utils"] = find_matching_issue(
            issues, "STYLE-001", "style", "info", file_exact="app/utils.py"
        )
        checks["has_STYLE_002_longline"] = find_matching_issue(
            issues, "STYLE-002", "style", "info", file_exact="app/longline.py"
        )

    # Markdown checks
    md_text = load_text(md_path) if md_exists else None
    checks["md_nonempty"] = is_nonempty_text(md_text)

    checks["md_has_sections"] = False
    checks["md_has_severity_words"] = False
    checks["md_mentions_calculate_discount_tests"] = False
    checks["md_mentions_files"] = False
    checks["md_mentions_frontend_app_js"] = False

    if is_nonempty_text(md_text):
        # Sections: Security, Performance, Style, Tests
        sections_ok = all(word.lower() in md_text.lower() for word in ["security", "performance", "style", "tests"])
        checks["md_has_sections"] = sections_ok

        # Must mention "Critical", "Warning", "Info"
        sev_words_ok = all(word.lower() in md_text.lower() for word in ["critical", "warning", "info"])
        checks["md_has_severity_words"] = sev_words_ok

        # Must mention calculate_discount and recommend adding tests
        calc_present = "calculate_discount" in md_text
        tests_word = re.search(r"\btest(s)?\b", md_text, re.IGNORECASE) is not None
        checks["md_mentions_calculate_discount_tests"] = calc_present and tests_word

        # Must reference files listed in the required findings
        files_required = ["app/auth.py", "app/db.py", "app/utils.py", "app/longline.py"]
        files_ok = all(f in md_text for f in files_required)
        checks["md_mentions_files"] = files_ok

        # At least one of frontend/app.js
        checks["md_mentions_frontend_app_js"] = ("frontend/app.js" in md_text)

    # PR template checks
    pr_text = load_text(pr_path) if pr_exists else None
    checks["pr_nonempty"] = is_nonempty_text(pr_text)
    checks["pr_has_sections"] = False
    if is_nonempty_text(pr_text):
        # Must contain "Review Summary" heading and sections for Security, Performance, Tests, Code Quality, Documentation, Deployment, Notes
        needed = ["review summary", "security", "performance", "tests", "code quality", "documentation", "deployment", "notes"]
        checks["pr_has_sections"] = all(n in pr_text.lower() for n in needed)

    # Calculate reward
    # Define which checks are required for any positive reward: the three files must exist and be valid/non-empty, and JSON must be valid.
    required_for_any = [
        "json_exists", "json_valid", "md_exists", "md_nonempty", "pr_exists", "pr_nonempty"
    ]
    if not all(checks.get(k, False) for k in required_for_any):
        reward = 0.0
    else:
        # Count all checks as part of scoring
        total_checks = 0
        passed_checks = 0
        for k, v in checks.items():
            total_checks += 1
            if v:
                passed_checks += 1
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Ensure reward is between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print final JSON result (single line)
    result = {"reward": reward}
    # Include all checks in output
    result.update({k: bool(v) for k, v in checks.items()})
    print(json.dumps(result))

if __name__ == "__main__":
    main()