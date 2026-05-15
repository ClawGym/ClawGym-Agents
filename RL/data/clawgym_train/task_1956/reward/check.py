import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

def to_float(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip())
        except Exception:
            return None
    return None

def load_json_file(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_gate_by_id(gates: List[Dict[str, Any]], gate_id: str) -> Optional[Dict[str, Any]]:
    for g in gates:
        if isinstance(g, dict) and g.get("id") == gate_id:
            return g
    return None

def find_check_by_id(gate: Dict[str, Any], check_id: str) -> Optional[Dict[str, Any]]:
    checks = gate.get("checks")
    if not isinstance(checks, list):
        return None
    for c in checks:
        if isinstance(c, dict) and c.get("id") == check_id:
            return c
    return None

def evidence_list_from_check(check: Dict[str, Any]) -> List[str]:
    ev = check.get("evidence")
    out = []
    if isinstance(ev, str):
        out.append(ev)
    elif isinstance(ev, list):
        for e in ev:
            if isinstance(e, str):
                out.append(e)
    return out

def metric_indicates_pass(metric: Any) -> bool:
    # Accept boolean True, numeric 1 or 0 failures, or strings indicating pass
    if metric is True:
        return True
    if isinstance(metric, (int, float)):
        # Numeric > 0 may not indicate pass; prefer 1 as True else False
        return float(metric) == 1.0 or float(metric) == 100.0
    if isinstance(metric, str):
        s = metric.strip().lower()
        return s in {"pass", "passed", "success", "ok", "green", "true"}
    if isinstance(metric, dict):
        # If provided as summary-like metric
        # Consider pass if failures/failed = 0 and passed True or status pass
        failures = None
        if "failures" in metric and isinstance(metric.get("failures"), (int, float)):
            failures = int(metric.get("failures"))
        elif "failed" in metric and isinstance(metric.get("failed"), (int, float)):
            failures = int(metric.get("failed"))
        status = str(metric.get("status", "")).lower() if "status" in metric else ""
        passed_flag = metric.get("passed", None)
        if failures == 0:
            return True
        if isinstance(passed_flag, bool) and passed_flag:
            return True
        if status in {"pass", "passed", "success", "green"}:
            return True
    return False

def parse_tests_summary_pass(summary: Any) -> Optional[bool]:
    # Attempt to determine if tests passed from input/repo/tests/summary.json
    try:
        if isinstance(summary, dict):
            # Direct indicators
            if isinstance(summary.get("passed"), bool):
                return summary.get("passed")
            if isinstance(summary.get("success"), bool):
                return summary.get("success")
            status = summary.get("status")
            if isinstance(status, str) and status.lower() in {"pass", "passed", "success", "green"}:
                return True
            # Failure counts
            for key in ["failures", "failed", "failureCount", "failedCount"]:
                if key in summary and isinstance(summary.get(key), (int, float)):
                    if int(summary.get(key)) == 0:
                        return True
                    else:
                        return False
            # Nested suites
            for suite_key in ["unit", "integration", "e2e", "smoke", "suites"]:
                if suite_key in summary:
                    val = summary[suite_key]
                    # suites may be list or dict
                    if isinstance(val, list):
                        if all(parse_tests_summary_pass(v) is not False for v in val):
                            # if none False and at least one True, consider True
                            any_true = any(parse_tests_summary_pass(v) is True for v in val)
                            return True if any_true else None
                        else:
                            return False
                    elif isinstance(val, dict):
                        sub = parse_tests_summary_pass(val)
                        if sub is not None:
                            return sub
        elif isinstance(summary, list):
            # List of suite results
            statuses = [parse_tests_summary_pass(x) for x in summary]
            if any(s is False for s in statuses):
                return False
            if any(s is True for s in statuses):
                return True
        return None
    except Exception:
        return None

def parse_coverage_overall(cov: Any) -> Optional[float]:
    # Try several common shapes to extract overall coverage percentage
    # Accept 0-100 scale
    # Direct numeric
    if isinstance(cov, (int, float)):
        return float(cov)
    if isinstance(cov, dict):
        # common keys
        # e.g., {"overall": 75}
        if "overall" in cov:
            val = cov["overall"]
            num = to_float(val)
            if num is not None:
                return num
            if isinstance(val, dict):
                # e.g., {"overall": {"coverage": 75}}
                for k in ["coverage", "percent", "percentage", "lines", "statements", "overall"]:
                    if k in val:
                        num = to_float(val[k])
                        if num is not None:
                            return num
        # e.g., {"coverage": 75}
        for k in ["coverage", "overallCoverage", "total", "percent", "percentage"]:
            if k in cov:
                num = to_float(cov[k])
                if num is not None:
                    return num
        # nested search for a plausible overall percentage
        # fallback: scan for a numeric between 0 and 100 with key hint
        for k, v in cov.items():
            if isinstance(v, (int, float)):
                num = float(v)
                if 0.0 <= num <= 100.0 and any(h in k.lower() for h in ["overall", "total", "coverage", "percent", "lines", "statements"]):
                    return num
            elif isinstance(v, dict):
                sub = parse_coverage_overall(v)
                if sub is not None:
                    return sub
    if isinstance(cov, list):
        # List of metrics: attempt find an "overall"
        for item in cov:
            sub = parse_coverage_overall(item)
            if sub is not None:
                return sub
    return None

def parse_vuln_counts(vulns: Any) -> Optional[Tuple[int, int]]:
    # Return (critical, high)
    try:
        if isinstance(vulns, dict):
            crit = None
            high = None
            for k in vulns.keys():
                lk = k.lower()
                if "critical" in lk and isinstance(vulns[k], (int, float)):
                    crit = int(vulns[k])
                if lk == "high" and isinstance(vulns[k], (int, float)):
                    high = int(vulns[k])
                if "high" in lk and high is None and isinstance(vulns[k], (int, float)):
                    high = int(vulns[k])
            # sometimes nested counts
            if crit is None or high is None:
                for v in vulns.values():
                    if isinstance(v, dict):
                        sub = parse_vuln_counts(v)
                        if sub is not None:
                            c, h = sub
                            if crit is None:
                                crit = c
                            if high is None:
                                high = h
            if crit is not None and high is not None:
                return (crit, high)
        elif isinstance(vulns, list):
            # Sum counts across items with severity field
            crit = 0
            high = 0
            seen = False
            for item in vulns:
                if isinstance(item, dict) and "severity" in item and "count" in item:
                    sev = str(item["severity"]).lower()
                    cnt = int(item["count"]) if isinstance(item["count"], (int, float)) else 0
                    if sev.startswith("crit"):
                        crit += cnt
                        seen = True
                    elif sev.startswith("high"):
                        high += cnt
                        seen = True
            if seen:
                return (crit, high)
        return None
    except Exception:
        return None

def parse_secrets_zero(secrets: Any) -> Optional[bool]:
    try:
        # Return True if no findings
        if secrets is None:
            return None
        if isinstance(secrets, dict):
            # Common shapes
            for k in ["findings", "secrets", "results", "matches", "detections"]:
                if k in secrets:
                    v = secrets[k]
                    if isinstance(v, list):
                        return len(v) == 0
                    if isinstance(v, (int, float)):
                        return int(v) == 0
            # count keys
            for k in ["count", "total", "numFindings", "num_findings"]:
                if k in secrets and isinstance(secrets[k], (int, float)):
                    return int(secrets[k]) == 0
        elif isinstance(secrets, list):
            return len(secrets) == 0
        elif isinstance(secrets, (int, float)):
            return int(secrets) == 0
        elif isinstance(secrets, str):
            s = secrets.strip().lower()
            if s in {"none", "no", "no_secrets", "no-findings", "zero", "0"}:
                return True
        return None
    except Exception:
        return None

def metric_indicates_zero_or_none(metric: Any) -> bool:
    if isinstance(metric, (int, float)):
        return float(metric) == 0.0
    if isinstance(metric, str):
        s = metric.strip().lower()
        return s in {"0", "zero", "none", "no", "no_findings", "no-findings"}
    if isinstance(metric, dict):
        # try to sum critical+high
        crit = metric.get("critical")
        high = metric.get("high")
        if isinstance(crit, (int, float)) and isinstance(high, (int, float)):
            return int(crit) == 0 and int(high) == 0
    if metric is True:
        # Some may encode True as "no findings" for secrets
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    out_json_path = os.path.join(output_dir, "docs", "quality", "quality-gate-report.json")
    out_md_path = os.path.join(output_dir, "docs", "quality", "quality-gate-report.md")

    cov_input_path = os.path.join(input_dir, "repo", "tests", "coverage.json")
    tests_summary_path = os.path.join(input_dir, "repo", "tests", "summary.json")
    vulns_input_path = os.path.join(input_dir, "repo", "security", "vulns.json")
    secrets_input_path = os.path.join(input_dir, "repo", "security", "secrets.json")

    required_gate_ids = {
        "build_dependency_health",
        "automated_testing_coverage",
        "security_supply_chain",
        "performance_efficiency",
        "maintainability_code_health",
        "release_readiness_operability",
    }

    checks: Dict[str, bool] = {
        "exists_json": False,
        "exists_md": False,
        "json_structure_valid": False,
        "gates_length_6": False,
        "gate_ids_present": False,
        "per_gate_objects_have_fields": False,
        "automated_testing_coverage_gate_warn": False,
        "coverage_check_metric_matches": False,
        "coverage_check_evidence": False,
        "tests_pass_check_metric": False,
        "tests_pass_check_evidence": False,
        "security_gate_pass": False,
        "dep_vulns_check_metric_zero": False,
        "dep_vulns_check_evidence": False,
        "secrets_check_metric_zero": False,
        "secrets_check_evidence": False,
        "blockers_present_and_empty": False,
        "evidence_paths_count_at_least_6": False,
        "markdown_has_headings": False,
        "markdown_lists_all_gateway_names": False,
        "markdown_has_blockers_section": False,
    }

    # Load outputs
    report_json = None
    if os.path.isfile(out_json_path):
        checks["exists_json"] = True
        report_json = load_json_file(out_json_path)

    report_md = None
    if os.path.isfile(out_md_path):
        checks["exists_md"] = True
        try:
            with open(out_md_path, "r", encoding="utf-8") as f:
                report_md = f.read()
        except Exception:
            report_md = None

    gates_list: List[Dict[str, Any]] = []
    if report_json and isinstance(report_json, dict):
        has_gates = isinstance(report_json.get("gates"), list)
        has_overall = isinstance(report_json.get("overall"), dict)
        has_blockers = isinstance(report_json.get("blockers"), list)
        if has_gates and has_overall and has_blockers:
            checks["json_structure_valid"] = True
            gates_list = report_json.get("gates", [])
            if isinstance(gates_list, list) and len(gates_list) == 6:
                checks["gates_length_6"] = True

            # gate ids present
            present_ids = set()
            for g in gates_list:
                if isinstance(g, dict) and isinstance(g.get("id"), str):
                    present_ids.add(g.get("id"))
            if required_gate_ids.issubset(present_ids):
                checks["gate_ids_present"] = True

            # per-gate fields
            per_gate_ok = True
            valid_statuses = {"PASS", "WARN", "FAIL"}
            for g in gates_list:
                if not isinstance(g, dict):
                    per_gate_ok = False
                    break
                if not isinstance(g.get("id"), str):
                    per_gate_ok = False
                    break
                if not isinstance(g.get("name"), str):
                    per_gate_ok = False
                    break
                score_val = g.get("score")
                if not isinstance(score_val, (int, float)):
                    per_gate_ok = False
                    break
                if float(score_val) < 0 or float(score_val) > 100:
                    per_gate_ok = False
                    break
                status_val = g.get("status")
                if not isinstance(status_val, str) or status_val not in valid_statuses:
                    per_gate_ok = False
                    break
                if not isinstance(g.get("checks"), list):
                    per_gate_ok = False
                    break
                # Check each check has id, metric, score, evidence
                for c in g.get("checks"):
                    if not isinstance(c, dict):
                        per_gate_ok = False
                        break
                    if not isinstance(c.get("id"), str):
                        per_gate_ok = False
                        break
                    # metric can be any type; skip type check but must exist
                    if "metric" not in c:
                        per_gate_ok = False
                        break
                    sc = c.get("score")
                    if not isinstance(sc, (int, float)):
                        per_gate_ok = False
                        break
                    if float(sc) < 0 or float(sc) > 100:
                        per_gate_ok = False
                        break
                    ev = c.get("evidence")
                    if not (isinstance(ev, str) or isinstance(ev, list)):
                        per_gate_ok = False
                        break
                if not per_gate_ok:
                    break
            if per_gate_ok:
                checks["per_gate_objects_have_fields"] = True

            # blockers present and empty
            blockers = report_json.get("blockers")
            if isinstance(blockers, list) and len(blockers) == 0:
                checks["blockers_present_and_empty"] = True

            # Specific gates validations only if we have needed inputs and gates
            at_gate = find_gate_by_id(gates_list, "automated_testing_coverage")
            sec_gate = find_gate_by_id(gates_list, "security_supply_chain")

            # Parse input metrics
            cov_json = load_json_file(cov_input_path)
            tests_summary_json = load_json_file(tests_summary_path)
            vulns_json = load_json_file(vulns_input_path)
            secrets_json = load_json_file(secrets_input_path)

            expected_coverage = parse_coverage_overall(cov_json) if cov_json is not None else None
            expected_tests_pass = parse_tests_summary_pass(tests_summary_json) if tests_summary_json is not None else None
            vuln_counts = parse_vuln_counts(vulns_json) if vulns_json is not None else None
            secrets_zero = parse_secrets_zero(secrets_json) if secrets_json is not None else None

            # Automated Testing & Coverage gate checks
            if at_gate and isinstance(at_gate.get("status"), str):
                if at_gate.get("status") == "WARN":
                    checks["automated_testing_coverage_gate_warn"] = True
                cov_check = find_check_by_id(at_gate, "coverage_overall")
                if cov_check and expected_coverage is not None:
                    metric_val = cov_check.get("metric")
                    metric_num = to_float(metric_val)
                    if metric_num is not None and abs(metric_num - float(expected_coverage)) <= 0.01:
                        checks["coverage_check_metric_matches"] = True
                    # evidence path
                    evs = evidence_list_from_check(cov_check)
                    if any(isinstance(e, str) and "input/repo/tests/coverage.json" in e for e in evs):
                        checks["coverage_check_evidence"] = True

                tests_check = find_check_by_id(at_gate, "tests_pass")
                if tests_check:
                    metric_ok = metric_indicates_pass(tests_check.get("metric"))
                    # Also must reflect actual input summary indicating pass
                    if metric_ok and (expected_tests_pass is True):
                        checks["tests_pass_check_metric"] = True
                    evs2 = evidence_list_from_check(tests_check)
                    if any(isinstance(e, str) and "input/repo/tests/summary.json" in e for e in evs2):
                        checks["tests_pass_check_evidence"] = True

            # Security & Supply-Chain gate checks
            if sec_gate and isinstance(sec_gate.get("status"), str):
                if sec_gate.get("status") == "PASS":
                    checks["security_gate_pass"] = True
                dep_check = find_check_by_id(sec_gate, "dependency_vulns_critical_high")
                if dep_check:
                    metric_val = dep_check.get("metric")
                    metric_zero_ok = metric_indicates_zero_or_none(metric_val)
                    # Also confirm from input that critical+high == 0
                    input_zero_ok = False
                    if vuln_counts is not None:
                        input_zero_ok = (vuln_counts[0] == 0 and vuln_counts[1] == 0)
                    if metric_zero_ok and input_zero_ok:
                        checks["dep_vulns_check_metric_zero"] = True
                    evs = evidence_list_from_check(dep_check)
                    if any(isinstance(e, str) and "input/repo/security/vulns.json" in e for e in evs):
                        checks["dep_vulns_check_evidence"] = True

                secrets_check = find_check_by_id(sec_gate, "secrets_scan")
                if secrets_check:
                    metric_val2 = secrets_check.get("metric")
                    metric_no_findings = metric_indicates_zero_or_none(metric_val2)
                    input_no_findings = (secrets_zero is True)
                    if metric_no_findings and input_no_findings:
                        checks["secrets_check_metric_zero"] = True
                    evs2 = evidence_list_from_check(secrets_check)
                    if any(isinstance(e, str) and "input/repo/security/secrets.json" in e for e in evs2):
                        checks["secrets_check_evidence"] = True

            # Evidence presence across all gates/checks
            # Count evidence entries referencing input/repo/
            evidence_refs_count = 0
            for g in gates_list:
                if not isinstance(g, dict):
                    continue
                for c in g.get("checks", []):
                    if not isinstance(c, dict):
                        continue
                    for ev in evidence_list_from_check(c):
                        if isinstance(ev, str) and "input/repo/" in ev:
                            evidence_refs_count += 1
            if evidence_refs_count >= 6:
                checks["evidence_paths_count_at_least_6"] = True

            # Markdown validations (need both MD and JSON loaded)
            if isinstance(report_md, str):
                md = report_md
                if ("## Summary" in md) and ("## Gateway Results" in md):
                    checks["markdown_has_headings"] = True
                # gate names presence: use names from JSON report to avoid strict matching
                gate_names = []
                for g in gates_list:
                    n = g.get("name")
                    if isinstance(n, str):
                        gate_names.append(n)
                if gate_names:
                    lower_md = md.lower()
                    names_present = all((name.lower() in lower_md) for name in gate_names)
                    if names_present:
                        checks["markdown_lists_all_gateway_names"] = True
                # blockers section or line detection
                lower_md2 = md.lower()
                if "blocking failures:" in lower_md2 or "blockers" in lower_md2:
                    checks["markdown_has_blockers_section"] = True

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total
    # No-op baseline: if outputs missing, ensure reward 0.0
    if not (checks["exists_json"] and checks["exists_md"]):
        reward = 0.0

    # Print result JSON
    result = {"reward": reward}
    # keep deterministic order
    for k in sorted(checks.keys()):
        result[k] = checks[k]
    print(json.dumps(result))

if __name__ == "__main__":
    main()