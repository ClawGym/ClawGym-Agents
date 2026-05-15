import json
import os
import sys

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def detect_critical_degraded_cases(suite):
    degraded_ids = set()
    cases = suite.get("cases", [])
    for c in cases:
        if not isinstance(c, dict):
            continue
        if not c.get("critical", False):
            continue
        after_output = c.get("after_output", "")
        before_output = c.get("before_output", "")
        # Simple deterministic indicators of failure or degradation
        indicators = [
            "TOOL_ERROR", "tool_error", "TOOL ERROR", "Exception", "Traceback",
            "failed", "failure", "not supported", "unsupported",
            "cannot", "can't", "missing fallback", "no fallback",
            "hallucinated", "retrieval miss", "MISSING_FALLBACK"
        ]
        # Consider degraded if any indicator appears in after_output and is worse than before_output (or before doesn't have it)
        after_flag = any(ind in after_output for ind in indicators)
        before_flag = any(ind in before_output for ind in indicators)
        if after_flag and not before_flag:
            cid = c.get("id")
            if isinstance(cid, str):
                degraded_ids.add(cid)
    return degraded_ids

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default; set True only after verification)
    checks = {
        "has_report_txt": False,
        "has_result_json": False,
        "result_json_parses": False,
        "result_has_required_keys": False,
        "suite_totals_match": False,
        "scorecard_numeric_fields": False,
        "deltas_numeric_fields": False,
        "risk_level_matches_input": False,
        "verdict_is_rollback": False,
        "failure_clusters_contains_standard": False,
        "top_regressions_refs_input": False,
        "report_contains_headings": False,
        "report_contains_rollback": False,
        # Input-only diagnostic (does not contribute positive reward)
        "input_has_critical_degraded": False,
    }

    # Load input suite
    suite_path = os.path.join(input_dir, "regression_suite.json")
    suite, suite_err = read_json_file(suite_path)
    input_loaded = suite is not None and isinstance(suite, dict)

    expected_total = None
    expected_critical = None
    input_ids = set()
    input_risk_level = None

    if input_loaded:
        cases = suite.get("cases", [])
        if isinstance(cases, list):
            expected_total = len(cases)
            expected_critical = sum(1 for c in cases if isinstance(c, dict) and c.get("critical", False))
            for c in cases:
                if isinstance(c, dict) and isinstance(c.get("id"), str):
                    input_ids.add(c["id"])
        input_risk_level = suite.get("risk_level")
        # Detect critical degraded cases (input diagnostic)
        degraded_ids = detect_critical_degraded_cases(suite)
        if degraded_ids:
            checks["input_has_critical_degraded"] = True

    # Verify outputs
    report_path = os.path.join(output_dir, "report.txt")
    result_path = os.path.join(output_dir, "result.json")

    if os.path.isfile(report_path):
        checks["has_report_txt"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_content = f.read()
            # Required headings
            required_headings = [
                "## Executive Summary",
                "## Suite Summary",
                "## Scorecard",
                "## Deltas",
                "## Top Regressions",
                "## Failure Clusters",
                "## Verdict",
                "## Recommended Fixes",
                "## Confidence",
                "## Limitations",
            ]
            if all(h in report_content for h in required_headings):
                checks["report_contains_headings"] = True
            if "rollback" in report_content.lower():
                checks["report_contains_rollback"] = True
        except Exception:
            pass

    result = None
    if os.path.isfile(result_path):
        checks["has_result_json"] = True
        result, err = read_json_file(result_path)
        if result is not None and isinstance(result, dict):
            checks["result_json_parses"] = True

    if checks["result_json_parses"]:
        # Validate required top-level keys and types
        required_top = {
            "change_summary": str,
            "risk_level": str,
            "confidence": str,
            "suite_summary": dict,
            "scorecard": dict,
            "deltas": dict,
            "verdict": str,
            "top_regressions": list,
            "failure_clusters": list,
            "recommended_fixes": list,
            "limitations": list,
        }
        has_required = True
        for k, t in required_top.items():
            if k not in result or not isinstance(result[k], t):
                has_required = False
                break
        if has_required and result.get("verdict") in {"go", "conditional_go", "no_go", "rollback"}:
            checks["result_has_required_keys"] = True

        # Suite totals and fields
        suite_summary = result.get("suite_summary", {}) if isinstance(result.get("suite_summary"), dict) else {}
        totals_ok = False
        if input_loaded and isinstance(suite_summary, dict):
            tc = suite_summary.get("total_cases")
            cc = suite_summary.get("critical_cases")
            mq = suite_summary.get("matching_quality")
            totals_ok = (
                isinstance(tc, int) and isinstance(cc, int) and isinstance(mq, str)
                and expected_total is not None and expected_critical is not None
                and tc == expected_total and cc == expected_critical
            )
        if totals_ok:
            checks["suite_totals_match"] = True

        # Scorecard numeric fields
        scorecard = result.get("scorecard", {}) if isinstance(result.get("scorecard"), dict) else {}
        sc_fields = [
            "overall_pass_rate",
            "critical_pass_rate",
            "soft_fail_rate",
            "tool_reliability_rate",
            "average_correctness",
            "average_relevance",
            "average_actionability",
        ]
        if isinstance(scorecard, dict) and all(is_number(scorecard.get(k)) for k in sc_fields):
            checks["scorecard_numeric_fields"] = True

        # Deltas numeric fields
        deltas = result.get("deltas", {}) if isinstance(result.get("deltas"), dict) else {}
        d_fields = [
            "overall_pass_rate_delta",
            "critical_pass_rate_delta",
            "tool_reliability_delta",
        ]
        if isinstance(deltas, dict) and all(is_number(deltas.get(k)) for k in d_fields):
            checks["deltas_numeric_fields"] = True

        # Risk level matches input
        if input_loaded and isinstance(result.get("risk_level"), str) and result.get("risk_level") == input_risk_level:
            checks["risk_level_matches_input"] = True

        # Verdict must be rollback
        if result.get("verdict") == "rollback":
            checks["verdict_is_rollback"] = True

        # Failure clusters include at least one standard name
        allowed_cluster_names = {
            "instruction_following_drift",
            "factuality_drop",
            "retrieval_miss",
            "tool_call_failure",
            "format_noncompliance",
            "missing_fallback",
            "hallucinated_capability",
        }
        clusters = result.get("failure_clusters", [])
        has_standard_cluster = False
        if isinstance(clusters, list):
            for c in clusters:
                if isinstance(c, dict):
                    name = c.get("name")
                    if isinstance(name, str) and name in allowed_cluster_names:
                        has_standard_cluster = True
                        break
        if has_standard_cluster:
            checks["failure_clusters_contains_standard"] = True

        # top_regressions references at least one case ID from input
        top_regs = result.get("top_regressions", [])
        referenced_ok = False
        if isinstance(top_regs, list) and input_ids:
            for item in top_regs:
                if isinstance(item, dict):
                    cid = item.get("case_id")
                    if isinstance(cid, str) and cid in input_ids:
                        referenced_ok = True
                        break
        if referenced_ok:
            checks["top_regressions_refs_input"] = True

    # Compute reward: only count checks that depend on output/
    countable_keys = [
        "has_report_txt",
        "has_result_json",
        "result_json_parses",
        "result_has_required_keys",
        "suite_totals_match",
        "scorecard_numeric_fields",
        "deltas_numeric_fields",
        "risk_level_matches_input",
        "verdict_is_rollback",
        "failure_clusters_contains_standard",
        "top_regressions_refs_input",
        "report_contains_headings",
        "report_contains_rollback",
    ]
    passed = sum(1 for k in countable_keys if checks.get(k, False))
    total = len(countable_keys)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if outputs are missing, reward must be 0.0
    if not os.path.isfile(report_path) and not os.path.isfile(result_path):
        reward = 0.0

    # Print single JSON object with reward first
    output = {"reward": reward}
    output.update(checks)
    print(json.dumps(output))

if __name__ == "__main__":
    main()