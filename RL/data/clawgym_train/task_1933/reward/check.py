import json
import os
import sys
from typing import Any, Dict, List

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def collect_suggestions(cov: Any) -> List[Dict]:
    suggestions = []
    if isinstance(cov, dict):
        # top-level suggestions (optional)
        if isinstance(cov.get("suggestions"), list):
            for s in cov["suggestions"]:
                if isinstance(s, dict):
                    suggestions.append(s)
        # per-file suggestions
        files = cov.get("files")
        if isinstance(files, list):
            for f in files:
                if isinstance(f, dict):
                    if isinstance(f.get("suggestions"), list):
                        for s in f["suggestions"]:
                            if isinstance(s, dict):
                                suggestions.append(s)
    return suggestions

def find_uncalled_decrement(cov: Any) -> bool:
    # Search in files[*].uncalled_functions for name == "decrement"
    if not isinstance(cov, dict):
        return False
    files = cov.get("files")
    if not isinstance(files, list):
        return False
    for f in files:
        if not isinstance(f, dict):
            continue
        ufs = f.get("uncalled_functions")
        if isinstance(ufs, list):
            for item in ufs:
                if isinstance(item, dict) and item.get("name") == "decrement":
                    return True
    return False

def suggestion_uncalled_decrement(cov: Any) -> bool:
    suggestions = collect_suggestions(cov)
    for s in suggestions:
        if s.get("type") == "uncalled_function":
            action = s.get("action", "")
            if isinstance(action, str) and "decrement" in action:
                return True
    return False

def suggestion_untaken_branch_classify(cov: Any) -> bool:
    suggestions = collect_suggestions(cov)
    for s in suggestions:
        if s.get("type") == "untaken_branch":
            action = s.get("action", "")
            if isinstance(action, str) and "classify" in action:
                return True
    return False

def has_all_substrings_ci(text: str, substrings: List[str]) -> bool:
    t = text.lower()
    return all(sub.lower() in t for sub in substrings)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        # coverage.json checks
        "coverage_json_exists": False,
        "coverage_json_valid": False,
        "coverage_json_has_summary_and_files": False,
        "coverage_json_uncalled_decrement_present": False,
        "coverage_json_suggestion_uncalled_decrement_present": False,
        "coverage_json_suggestion_untaken_branch_classify_present": False,
        # coverage.md checks
        "coverage_md_exists": False,
        "coverage_md_has_sections": False,
        "coverage_md_mentions_decrement_and_classify": False,
        "coverage_md_mentions_einsufficient_and_expected_failure": False,
        # tests/vault_tests.md checks
        "tests_md_exists": False,
        "tests_md_has_decrement_test": False,
        "tests_md_has_two_classify_calls": False,
        "tests_md_has_expected_failure_einsufficient": False,
        # SECURITY.md checks
        "security_md_exists": False,
        "security_md_has_required_sections": False,
        "security_md_mentions_access_control_and_overflow_underflow": False,
    }

    # Paths
    cov_json_path = os.path.join(output_dir, "coverage.json")
    cov_md_path = os.path.join(output_dir, "coverage.md")
    tests_md_path = os.path.join(output_dir, "tests", "vault_tests.md")
    sec_md_path = os.path.join(output_dir, "SECURITY.md")

    # coverage.json validations
    if os.path.isfile(cov_json_path):
        checks["coverage_json_exists"] = True
        cov = load_json(cov_json_path)
        if isinstance(cov, dict):
            checks["coverage_json_valid"] = True
            has_summary = "summary" in cov and isinstance(cov.get("summary"), dict)
            has_files = "files" in cov and isinstance(cov.get("files"), list)
            checks["coverage_json_has_summary_and_files"] = has_summary and has_files

            # uncalled decrement present
            if has_files:
                if find_uncalled_decrement(cov):
                    checks["coverage_json_uncalled_decrement_present"] = True

            # suggestions checks
            if suggestion_uncalled_decrement(cov):
                checks["coverage_json_suggestion_uncalled_decrement_present"] = True
            if suggestion_untaken_branch_classify(cov):
                checks["coverage_json_suggestion_untaken_branch_classify_present"] = True

    # coverage.md validations
    if os.path.isfile(cov_md_path):
        checks["coverage_md_exists"] = True
        cov_md = read_text(cov_md_path)
        if cov_md:
            # Must reference Uncalled, Untaken, and Uncovered
            if has_all_substrings_ci(cov_md, ["Uncalled", "Untaken", "Uncovered"]):
                checks["coverage_md_has_sections"] = True
            # Mentions decrement and classify
            if has_all_substrings_ci(cov_md, ["decrement", "classify"]):
                checks["coverage_md_mentions_decrement_and_classify"] = True
            # Mentions EInsufficientBalance and recommends expected_failure
            if has_all_substrings_ci(cov_md, ["einsufficientbalance", "expected_failure"]):
                checks["coverage_md_mentions_einsufficient_and_expected_failure"] = True

    # tests/vault_tests.md validations
    if os.path.isfile(tests_md_path):
        checks["tests_md_exists"] = True
        tests_md = read_text(tests_md_path)
        if tests_md:
            # A #[test] that calls decrement(
            if ("#[test]" in tests_md) and ("decrement(" in tests_md):
                checks["tests_md_has_decrement_test"] = True
            # Two classify( occurrences
            classify_count = tests_md.count("classify(")
            if classify_count >= 2:
                checks["tests_md_has_two_classify_calls"] = True
            # One #[expected_failure ...] referencing EInsufficientBalance
            if ("#[expected_failure" in tests_md) and ("EInsufficientBalance" in tests_md):
                checks["tests_md_has_expected_failure_einsufficient"] = True

    # SECURITY.md validations
    if os.path.isfile(sec_md_path):
        checks["security_md_exists"] = True
        sec_md = read_text(sec_md_path)
        if sec_md:
            if has_all_substrings_ci(sec_md, ["Security Analysis", "Summary", "Findings", "Tested Edge Cases"]):
                checks["security_md_has_required_sections"] = True
            # Mentions Access Control and either overflow or underflow
            has_access_control = "access control" in sec_md.lower()
            has_over_under = ("overflow" in sec_md.lower()) or ("underflow" in sec_md.lower())
            if has_access_control and has_over_under:
                checks["security_md_mentions_access_control_and_overflow_underflow"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
    # Ensure exact 0.0 when no artifacts (no-op baseline)
    # If none of the artifact-dependent checks pass, reward stays 0.0
    # Clip to [0,1]
    reward = max(0.0, min(1.0, float(f"{reward:.6f}")))

    # Print single JSON object with "reward" first
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()