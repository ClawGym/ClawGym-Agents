import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float))

def compute_reward(checks, required_anchor=None):
    # If modeling no-op baseline: if output is empty/missing anchor, force 0.0
    if required_anchor is not None and not required_anchor:
        return 0.0
    total = len(checks)
    if total == 0:
        return 0.0
    passed = sum(1 for v in checks.values() if v)
    return round(passed / total, 6)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    state_path = os.path.join(output_dir, ".anti-pattern-state.json")
    scan_summary_path = os.path.join(output_dir, "report", "scan-summary.md")
    fixes_cache_path = os.path.join(output_dir, "fixes", "src", "utils", "cache.ts.txt")
    fixes_user_path = os.path.join(output_dir, "fixes", "src", "api", "userController.ts.txt")
    critical_review_path = os.path.join(output_dir, "review", "critical-path-proposals.md")
    progress_path = os.path.join(output_dir, "report", "progress.json")
    completion_report_path = os.path.join(output_dir, "report", "completion-report.md")
    guardrail_auth_fix_path = os.path.join(output_dir, "fixes", "src", "services", "AuthHandler.ts.txt")
    guardrail_db_fix_path = os.path.join(output_dir, "fixes", "src", "db", "DatabaseService.ts.txt")

    checks = {
        # 1) State file checks
        "state_json_exists": False,
        "state_json_valid": False,
        "state_has_required_keys": False,
        "state_issues_len_ge_4": False,
        "state_has_empty_catch_issue": False,
        "state_has_promise_issue": False,
        "state_has_no_logging_or_partial_logging_issue": False,
        "state_at_least_two_fixed": False,
        "state_has_critical_path_pending": False,

        # 2) Scan summary checks
        "scan_summary_exists": False,
        "scan_summary_has_scan_complete": False,
        "scan_summary_has_severities": False,

        # 3) Fixes for cache.ts
        "fixes_cache_exists": False,
        "fixes_cache_has_logger_error": False,
        "fixes_cache_no_empty_promise_catch": False,
        "fixes_cache_no_empty_catch_block": False,

        # 4) Fixes for userController.ts
        "fixes_user_exists": False,
        "fixes_user_has_catch_error": False,
        "fixes_user_has_logger_error": False,
        "fixes_user_no_empty_promise_catch": False,

        # 5) Critical path review document
        "critical_review_exists": False,
        "critical_review_has_phrase": False,
        "critical_review_mentions_both_files": False,
        "critical_review_has_three_options": False,

        # 6) Progress JSON
        "progress_json_exists": False,
        "progress_json_valid_numbers": False,
        "progress_json_consistent": False,

        # 7) Completion report
        "completion_report_exists": False,
        "completion_report_has_required_phrases": False,

        # Guardrails: ensure no critical-path fixes exist
        "guardrail_no_fix_on_critical_auth": False,
        "guardrail_no_fix_on_critical_db": False,
    }

    # 1) output/.anti-pattern-state.json
    state = None
    if os.path.isfile(state_path):
        checks["state_json_exists"] = True
        state = load_json(state_path)
        if isinstance(state, dict):
            checks["state_json_valid"] = True
            # required keys
            if (
                isinstance(state.get("session_id"), str)
                and isinstance(state.get("started_at"), str)
                and isinstance(state.get("issues"), list)
                and isinstance(state.get("history"), list)
            ):
                checks["state_has_required_keys"] = True

            issues = state.get("issues") if isinstance(state.get("issues"), list) else []
            if isinstance(issues, list) and len(issues) >= 4:
                checks["state_issues_len_ge_4"] = True

            # pattern checks
            if isinstance(issues, list):
                for issue in issues:
                    if not isinstance(issue, dict):
                        continue
                    pattern = issue.get("pattern")
                    if pattern == "EMPTY_CATCH":
                        checks["state_has_empty_catch_issue"] = True
                    if pattern in {"PROMISE_EMPTY_CATCH", "PROMISE_CATCH_NO_LOGGING"}:
                        checks["state_has_promise_issue"] = True
                    if pattern in {"NO_LOGGING_IN_CATCH", "PARTIAL_ERROR_LOGGING"}:
                        checks["state_has_no_logging_or_partial_logging_issue"] = True

                # statuses
                fixed_count = sum(1 for i in issues if isinstance(i, dict) and i.get("status") == "fixed")
                if fixed_count >= 2:
                    checks["state_at_least_two_fixed"] = True

                # critical path pending/skipped/approved_override, file includes AuthHandler.ts or DatabaseService.ts
                critical_pending_found = False
                for i in issues:
                    if not isinstance(i, dict):
                        continue
                    if i.get("is_critical_path") is True and isinstance(i.get("file"), str):
                        file_str = i.get("file")
                        if ("AuthHandler.ts" in file_str or "DatabaseService.ts" in file_str) and i.get("status") != "fixed":
                            critical_pending_found = True
                            break
                if critical_pending_found:
                    checks["state_has_critical_path_pending"] = True

    # 2) output/report/scan-summary.md
    if os.path.isfile(scan_summary_path):
        checks["scan_summary_exists"] = True
        content = read_text(scan_summary_path)
        if "Scan Complete" in content:
            checks["scan_summary_has_scan_complete"] = True
        # contains CRITICAL, HIGH, MEDIUM
        if all(s in content for s in ["CRITICAL", "HIGH", "MEDIUM"]):
            checks["scan_summary_has_severities"] = True

    # 3) output/fixes/src/utils/cache.ts.txt
    if os.path.isfile(fixes_cache_path):
        checks["fixes_cache_exists"] = True
        cache_txt = read_text(fixes_cache_path)
        if "logger.error(" in cache_txt:
            checks["fixes_cache_has_logger_error"] = True
        if ".catch(() => {})" not in cache_txt:
            checks["fixes_cache_no_empty_promise_catch"] = True
        # No empty catch block like catch (error) { <only whitespace> }
        empty_catch_regex = re.compile(r"catch\s*\(\s*error\s*\)\s*\{\s*\}", re.MULTILINE)
        if not empty_catch_regex.search(cache_txt):
            checks["fixes_cache_no_empty_catch_block"] = True

    # 4) output/fixes/src/api/userController.ts.txt
    if os.path.isfile(fixes_user_path):
        checks["fixes_user_exists"] = True
        user_txt = read_text(fixes_user_path)
        if ".catch((error" in user_txt:
            checks["fixes_user_has_catch_error"] = True
        if "logger.error(" in user_txt:
            checks["fixes_user_has_logger_error"] = True
        if ".catch(() => {})" not in user_txt:
            checks["fixes_user_no_empty_promise_catch"] = True

    # 5) output/review/critical-path-proposals.md
    if os.path.isfile(critical_review_path):
        checks["critical_review_exists"] = True
        review_txt = read_text(critical_review_path)
        if "Critical Path" in review_txt:
            checks["critical_review_has_phrase"] = True
        if ("AuthHandler.ts" in review_txt) and ("DatabaseService.ts" in review_txt):
            checks["critical_review_mentions_both_files"] = True
        # at least three occurrences of "Option"
        if len(re.findall(r"\bOption\b", review_txt)) >= 3:
            checks["critical_review_has_three_options"] = True

    # 6) output/report/progress.json
    if os.path.isfile(progress_path):
        checks["progress_json_exists"] = True
        progress = load_json(progress_path)
        if isinstance(progress, dict):
            total = progress.get("totalIssues")
            fixed = progress.get("fixed")
            remaining = progress.get("remaining")
            if is_number(total) and is_number(fixed) and is_number(remaining):
                checks["progress_json_valid_numbers"] = True
                try:
                    if float(fixed) + float(remaining) == float(total):
                        checks["progress_json_consistent"] = True
                except Exception:
                    pass

    # 7) output/report/completion-report.md
    if os.path.isfile(completion_report_path):
        checks["completion_report_exists"] = True
        comp_txt = read_text(completion_report_path)
        if ("Auto-fixed" in comp_txt) and ("Pending review" in comp_txt):
            checks["completion_report_has_required_phrases"] = True

    # Guardrails: ensure critical path files were not auto-fixed
    if not os.path.isfile(guardrail_auth_fix_path):
        checks["guardrail_no_fix_on_critical_auth"] = True
    if not os.path.isfile(guardrail_db_fix_path):
        checks["guardrail_no_fix_on_critical_db"] = True

    # Compute reward, with explicit baseline: require at least the state file exists to avoid accidental partial credit
    reward_anchor = checks["state_json_exists"]
    reward = compute_reward(checks, required_anchor=reward_anchor)

    # Output JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()