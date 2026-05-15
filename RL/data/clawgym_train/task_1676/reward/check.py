import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Dict


def _read_text(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False, ""


def _load_json(path: Path) -> Tuple[bool, Optional[dict]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return True, data
        return False, None
    except Exception:
        return False, None


def _count_words(s: str) -> int:
    return len([w for w in re.split(r"\s+", s.strip()) if w])


def _parse_raw_messages(text: str) -> List[str]:
    messages: List[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*-\s+(.*)$", line)
        if m:
            messages.append(m.group(1).strip())
    return messages


def _parse_rewritten_pairs(text: str) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    before: Optional[str] = None
    after: Optional[str] = None
    collecting_after = False
    for line in text.splitlines():
        if line.strip().startswith("Before:"):
            if before is not None and after is not None:
                pairs.append((before.strip(), after.strip()))
                after = None
            before = line.split("Before:", 1)[1].strip()
            collecting_after = False
        elif line.strip().startswith("After:"):
            after = line.split("After:", 1)[1].strip()
            collecting_after = True
        else:
            if collecting_after and after is not None:
                after = (after + "\n" + line.rstrip()).strip()
            elif before is not None and after is None:
                before = (before + "\n" + line.rstrip()).strip()
    if before is not None and after is not None:
        pairs.append((before.strip(), after.strip()))
    return pairs


def _extract_metrics_from_summary(text: str) -> Dict[str, Optional[int]]:
    def find_first_int_after(word: str) -> Optional[int]:
        m = re.search(rf"(?i)\b{word}\b[^0-9]*([0-9]+)", text)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
        return None

    return {
        "total": find_first_int_after("total"),
        "passed": find_first_int_after("passed"),
        "failed": find_first_int_after("failed"),
    }


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _has_assertion_messages(test_text: str) -> bool:
    if re.search(r"assert[^,\n]+,\s*(['\"]).+?\1", test_text):
        return True
    if re.search(r"\bmsg\s*=", test_text):
        return True
    if re.search(r"self\.assert\w+\s*\([^)]*,[^)]*,[^)]*\)", test_text):
        return True
    if re.search(r"\bpytest\.fail\s*\(\s*(['\"]).+?\1\s*\)", test_text):
        return True
    return False


def _normalize_title_coverage(test_text: str) -> Dict[str, float]:
    coverage = {
        "nt_trims_whitespace": 0.0,
        "nt_collapse_spaces": 0.0,
        "nt_title_case": 0.0,
        "nt_preserve_acronyms": 0.0,
        "nt_empty_or_whitespace_to_empty": 0.0,
    }

    calls = re.findall(r"normalize_title\(\s*(['\"])(.*?)\1", test_text, flags=re.S)
    args = [arg for _, arg in calls]

    for arg in args:
        if arg != arg.strip():
            coverage["nt_trims_whitespace"] = 1.0
            break
        if re.match(r"^\s+.*|.*\s+$", arg, flags=re.S):
            coverage["nt_trims_whitespace"] = 1.0
            break

    for arg in args:
        if "  " in arg or "\t" in arg:
            coverage["nt_collapse_spaces"] = 1.0
            break

    if ("hello world" in test_text.lower()) and (re.search(r"\bHello World\b", test_text)):
        coverage["nt_title_case"] = 1.0
    else:
        if ("title" in test_text.lower() and "case" in test_text.lower() and "normalize_title(" in test_text):
            coverage["nt_title_case"] = 1.0

    if re.search(r"normalize_title\(\s*(['\"]).*(\bAPI\b|\bUX\b).*\1", test_text):
        coverage["nt_preserve_acronyms"] = 1.0

    for arg in args:
        if arg.strip() == "" and re.fullmatch(r"\s*", arg or ""):
            coverage["nt_empty_or_whitespace_to_empty"] = 1.0
            break

    return coverage


def _calculate_discount_coverage(test_text: str) -> Dict[str, float]:
    coverage = {
        "cd_value_error_negative_price": 0.0,
        "cd_value_error_percent_out_of_range": 0.0,
        "cd_rounding_to_two_decimals": 0.0,
        "cd_correct_result_case": 0.0,
    }
    if re.search(r"calculate_discount\(\s*-\d", test_text) and ("ValueError" in test_text):
        coverage["cd_value_error_negative_price"] = 1.0

    if ((re.search(r"calculate_discount\([^)]*(110|101|120)\b", test_text) or re.search(r"percent\s*=\s*(110|101|120)\b", test_text) or re.search(r"calculate_discount\([^)]*,\s*-\d", test_text)) and ("ValueError" in test_text)):
        coverage["cd_value_error_percent_out_of_range"] = 1.0

    if ("8.99" in test_text and re.search(r"calculate_discount\([^)]*9\.99[^)]*10", test_text)) or ("round(" in test_text and re.search(r",\s*2\)", test_text)):
        coverage["cd_rounding_to_two_decimals"] = 1.0

    if re.search(r"calculate_discount\([^)]*100[^)]*25", test_text) and (("75.00" in test_text) or (re.search(r"\b75(\.0+)?\b", test_text))):
        coverage["cd_correct_result_case"] = 1.0

    return coverage


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "tests_file_exists": 0.0,
        "tests_reference_functions": 0.0,
        "tests_have_assertion_messages": 0.0,
        "normalize_title_trims_whitespace_case_present": 0.0,
        "normalize_title_collapse_spaces_case_present": 0.0,
        "normalize_title_title_case_case_present": 0.0,
        "normalize_title_preserve_acronyms_case_present": 0.0,
        "normalize_title_empty_to_empty_case_present": 0.0,
        "calculate_discount_negative_price_validation_present": 0.0,
        "calculate_discount_percent_range_validation_present": 0.0,
        "calculate_discount_rounding_case_present": 0.0,
        "calculate_discount_correct_result_case_present": 0.0,
        "test_results_json_exists_and_valid": 0.0,
        "test_results_counts_consistent": 0.0,
        "status_summary_exists_and_title": 0.0,
        "status_summary_metrics_match_results": 0.0,
        "status_summary_lists_failed_tests": 0.0,
        "status_summary_has_next_steps": 0.0,
        "rewritten_messages_exists": 0.0,
        "rewritten_pairs_count_matches_input": 0.0,
        "rewritten_before_exact_match": 0.0,
        "rewritten_after_30pct_shorter": 0.0,
        "email_draft_exists": 0.0,
        "email_has_headers_to_cc_subject": 0.0,
        "email_counts_match_results": 0.0,
        "email_references_artifacts": 0.0,
    }

    # 1) Tests file checks
    tests_path = workspace / "tests" / "test_utils.py"
    ok_tests, tests_text = _read_text(tests_path)
    if ok_tests:
        scores["tests_file_exists"] = 1.0
        if "normalize_title" in tests_text and "calculate_discount" in tests_text:
            scores["tests_reference_functions"] = 1.0
        if _has_assertion_messages(tests_text):
            scores["tests_have_assertion_messages"] = 1.0

        nt_cov = _normalize_title_coverage(tests_text)
        scores["normalize_title_trims_whitespace_case_present"] = nt_cov["nt_trims_whitespace"]
        scores["normalize_title_collapse_spaces_case_present"] = nt_cov["nt_collapse_spaces"]
        scores["normalize_title_title_case_case_present"] = nt_cov["nt_title_case"]
        scores["normalize_title_preserve_acronyms_case_present"] = nt_cov["nt_preserve_acronyms"]
        scores["normalize_title_empty_to_empty_case_present"] = nt_cov["nt_empty_or_whitespace_to_empty"]

        cd_cov = _calculate_discount_coverage(tests_text)
        scores["calculate_discount_negative_price_validation_present"] = cd_cov["cd_value_error_negative_price"]
        scores["calculate_discount_percent_range_validation_present"] = cd_cov["cd_value_error_percent_out_of_range"]
        scores["calculate_discount_rounding_case_present"] = cd_cov["cd_rounding_to_two_decimals"]
        scores["calculate_discount_correct_result_case_present"] = cd_cov["cd_correct_result_case"]

    # 2) Test results JSON checks
    results_path = workspace / "output" / "test_results.json"
    ok_json, results = _load_json(results_path)
    if ok_json and isinstance(results, dict):
        required_fields = {"total": int, "passed": int, "failed": int, "failed_tests": list, "timestamp": str}
        valid = True
        for k, t in required_fields.items():
            if k not in results or not isinstance(results[k], t):
                valid = False
                break
        if valid and not all(isinstance(x, str) for x in results.get("failed_tests", [])):
            valid = False
        if valid and (not isinstance(results.get("timestamp", ""), str) or not results.get("timestamp", "").strip()):
            valid = False
        if valid:
            scores["test_results_json_exists_and_valid"] = 1.0
            total_ok = (results["total"] == results["passed"] + results["failed"])
            failed_len_ok = (len(results["failed_tests"]) == results["failed"])
            if total_ok and failed_len_ok:
                scores["test_results_counts_consistent"] = 1.0

    # 3) Status summary checks
    summary_path = workspace / "output" / "test_status_summary.md"
    ok_summary, summary_text = _read_text(summary_path)
    if ok_summary:
        if _first_nonempty_line(summary_text) == "Unit Test Summary for utils.py":
            scores["status_summary_exists_and_title"] = 1.0

        if ok_json and isinstance(results, dict):
            metrics = _extract_metrics_from_summary(summary_text)
            if all(metrics.get(k) is not None for k in ("total", "passed", "failed")):
                if (
                    metrics["total"] == results["total"]
                    and metrics["passed"] == results["passed"]
                    and metrics["failed"] == results["failed"]
                ):
                    scores["status_summary_metrics_match_results"] = 1.0
            failed_tests_list = results.get("failed_tests", [])
            if all(((ft in summary_text) for ft in failed_tests_list)) and (len(failed_tests_list) == results.get("failed", -1)):
                scores["status_summary_lists_failed_tests"] = 1.0

        if re.search(r"(?i)next steps", summary_text) and (re.search(r"(?i)acronym", summary_text) or re.search(r"(?i)validation", summary_text) or "normalize_title" in summary_text or "calculate_discount" in summary_text):
            scores["status_summary_has_next_steps"] = 1.0

    # 4) Rewritten messages checks
    rewritten_path = workspace / "output" / "rewritten_messages.md"
    ok_rewritten, rewritten_text = _read_text(rewritten_path)
    if ok_rewritten:
        scores["rewritten_messages_exists"] = 1.0
        ok_raw, raw_text = _read_text(workspace / "input" / "notes" / "raw_messages.md")
        raw_msgs = _parse_raw_messages(raw_text) if ok_raw else []
        pairs = _parse_rewritten_pairs(rewritten_text)
        if raw_msgs and len(pairs) == len(raw_msgs):
            scores["rewritten_pairs_count_matches_input"] = 1.0
            if all(pairs[i][0].strip() == raw_msgs[i].strip() for i in range(len(raw_msgs))):
                scores["rewritten_before_exact_match"] = 1.0
            shorter_ok = True
            for before, after in pairs:
                bw = _count_words(before)
                aw = _count_words(after)
                if bw == 0 or aw > 0.7 * bw:
                    shorter_ok = False
                    break
            if shorter_ok:
                scores["rewritten_after_30pct_shorter"] = 1.0

    # 5) Email draft checks
    email_path = workspace / "output" / "email_draft.md"
    ok_email, email_text = _read_text(email_path)
    if ok_email:
        scores["email_draft_exists"] = 1.0
        has_subject = re.search(r"^Subject:\s*Test Results for utils\.py\s*$", email_text, flags=re.M) is not None
        has_to = re.search(r"^To:\s*engineering@local\s*$", email_text, flags=re.M) is not None
        has_cc = re.search(r"^Cc:\s*pm@local\s*$", email_text, flags=re.M) is not None
        if has_subject and has_to and has_cc:
            scores["email_has_headers_to_cc_subject"] = 1.0
        if ok_json and isinstance(results, dict):
            counts_present = (
                str(results["total"]) in email_text
                and str(results["passed"]) in email_text
                and str(results["failed"]) in email_text
            )
            if counts_present:
                scores["email_counts_match_results"] = 1.0
        refs_ok = all(p in email_text for p in [
            "tests/test_utils.py",
            "output/test_results.json",
            "output/test_status_summary.md",
            "output/rewritten_messages.md",
        ])
        if refs_ok:
            scores["email_references_artifacts"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()