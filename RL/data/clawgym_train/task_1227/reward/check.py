import json
import os
import re
import sys
from typing import Dict, Any, List, Tuple

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_iso8601_utc(s: str) -> bool:
    # Basic ISO 8601 check: YYYY-MM-DDTHH:MM:SSZ
    return isinstance(s, str) and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", s) is not None

def severity_index(sev: str) -> int:
    order = ["CLEAN", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    s = (sev or "").upper()
    return order.index(s) if s in order else -1

def compute_rule_result(policy_rule: Dict[str, Any], comp: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Returns (passed, details)
    Implements rule logic per specification using only comp data fields:
    - scanner_severity: comp["findings"] list with "severity"
    - trust_level: comp["trust_level"]
    - pattern_absent: scan comp["code_text"] for any forbidden pattern (case-insensitive)
    - checksums_present: comp["checksums"] boolean
    - version_pinned: comp["dependencies"] list of strings (each must contain '==' or '>=')
    """
    check = policy_rule.get("check")
    params = policy_rule.get("params", {}) or {}
    details: Dict[str, Any] = {}
    # Default data fallbacks
    findings = comp.get("findings") or []
    code_text = comp.get("code_text") or ""
    trust_level = (comp.get("trust_level") or "").upper()
    checksums_flag = bool(comp.get("checksums"))
    deps = comp.get("dependencies") or []

    if check == "scanner_severity":
        max_sev = params.get("max_severity", "CRITICAL")
        max_count = int(params.get("max_count", 0))
        threshold_idx = severity_index(max_sev)
        bad = [f for f in findings if severity_index(f.get("severity", "")) >= threshold_idx]
        details = {
            "max_severity": max_sev,
            "max_count": max_count,
            "violations": len(bad),
        }
        return (len(bad) <= max_count), details

    if check == "trust_level":
        # Pass only if TRUSTED or VERIFIED
        passed = trust_level in ("TRUSTED", "VERIFIED")
        details = {"trust_level": trust_level, "min_level": "TRUSTED"}
        return passed, details

    if check == "pattern_absent":
        patterns = [str(p) for p in (params.get("patterns") or [])]
        lowered = code_text.lower()
        found: List[Dict[str, Any]] = []
        for p in patterns:
            if p.lower() in lowered:
                found.append({"pattern": p})
        details = {"patterns_checked": patterns, "found_count": len(found), "found": found[:10]}
        return (len(found) == 0), details

    if check == "checksums_present":
        details = {"checksums_flag": checksums_flag}
        return checksums_flag, details

    if check == "version_pinned":
        # non-empty dependency lines must contain == or >=
        unpinned = []
        for d in deps:
            ds = str(d).strip()
            if not ds:
                continue
            if ("==" not in ds) and (">=" not in ds):
                unpinned.append(ds)
        details = {"total_deps": len([d for d in deps if str(d).strip()]), "unpinned": unpinned}
        return (len(unpinned) == 0), details

    # Unknown check type -> fail
    details = {"note": f"Unknown check type: {check}"}
    return False, details

def apply_exemption(skill: str, rule_name: str, exemptions_index: Dict[Tuple[str, str], bool]) -> bool:
    return exemptions_index.get((skill, rule_name), False)

def compute_expected_assessment(skill_name: str, policy_name: str, policy: Dict[str, Any], comp: Dict[str, Any], exemptions_index: Dict[Tuple[str, str], bool]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    rules = policy.get("rules", [])
    for rule in rules:
        rule_name = rule.get("name", "")
        passed, details = compute_rule_result(rule, comp)
        exempted = (not passed) and apply_exemption(skill_name, rule_name, exemptions_index)
        results.append({
            "rule": rule_name,
            "severity": rule.get("severity", "medium"),
            "frameworks": rule.get("frameworks", []),
            "passed": passed,
            "exempted": exempted,
            "details": details,
        })

    rules_total = len(results)
    rules_passed = sum(1 for r in results if r["passed"])
    rules_exempted = sum(1 for r in results if not r["passed"] and r["exempted"])
    rules_failed = sum(1 for r in results if not r["passed"] and not r["exempted"])

    if rules_failed == 0 and rules_exempted == 0:
        status = "COMPLIANT"
    elif rules_failed == 0 and rules_exempted > 0:
        status = "EXEMPTED"
    else:
        status = "NON-COMPLIANT"

    assessment = {
        "skill": skill_name,
        "policy": policy_name,
        "status": status,
        # assessed_at will be validated from output, not computed here
        "rules_total": rules_total,
        "rules_passed": rules_passed,
        "rules_failed": rules_failed,
        "rules_exempted": rules_exempted,
        "results": results,
    }
    return assessment

def index_exemptions(exemptions_payload: Any) -> Dict[Tuple[str, str], bool]:
    idx: Dict[Tuple[str, str], bool] = {}
    if not exemptions_payload:
        return idx
    # Expecting something like {"exemptions":[{"skill":"net-monitor","rule":"no-network-calls", ...}, ...]}
    ex_list = []
    if isinstance(exemptions_payload, dict):
        if isinstance(exemptions_payload.get("exemptions"), list):
            ex_list = exemptions_payload["exemptions"]
        elif isinstance(exemptions_payload.get("items"), list):
            ex_list = exemptions_payload["items"]
    elif isinstance(exemptions_payload, list):
        ex_list = exemptions_payload

    for e in ex_list:
        skill = e.get("skill") or e.get("component") or e.get("name")
        rule = e.get("rule")
        if isinstance(skill, str) and isinstance(rule, str):
            idx[(skill, rule)] = True
    return idx

def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Prepare checks dict
    checks = {
        "file_acme_exists": False,
        "file_net_exists": False,
        "file_calc_exists": False,
        "schema_all_valid": False,
        "policy_field_ok": False,
        "rules_coverage_ok": False,
        "counts_consistent": False,
        "statuses_expected": False,
        "frameworks_ok": False,
        "report_valid": False,
        "report_totals_ok": False,
        "report_frameworks_ok": False,
        "summary_ok": False,
        "remediations_ok": False,
    }

    # Paths
    policy_path = os.path.join(input_dir, "policies", "production.json")
    skills_input_dir = os.path.join(input_dir, "skills")
    exemptions_path = os.path.join(input_dir, "exemptions.json")

    # Load references
    policy = load_json(policy_path) or {}
    policy_name = policy.get("name") or "production"
    policy_description = policy.get("description", "")
    policy_rules = policy.get("rules", [])
    policy_rule_map = {r.get("name"): r for r in policy_rules}
    rule_names = [r.get("name") for r in policy_rules if r.get("name")]

    # Load components input
    comp_files = {
        "acme-budget-tracker": os.path.join(skills_input_dir, "acme-budget-tracker.json"),
        "net-monitor": os.path.join(skills_input_dir, "net-monitor.json"),
        "calc-engine": os.path.join(skills_input_dir, "calc-engine.json"),
    }
    comps = {name: (load_json(path) or {}) for name, path in comp_files.items()}

    # Load exemptions
    exemptions_payload = load_json(exemptions_path) or {}
    exemptions_idx = index_exemptions(exemptions_payload)

    # Compute expected assessments from inputs
    expected = {}
    for name in comp_files.keys():
        expected[name] = compute_expected_assessment(name, "production", policy, comps.get(name, {}), exemptions_idx)

    # Output assessment paths
    out_assess_dir = os.path.join(output_dir, "assessments")
    acme_assess_path = os.path.join(out_assess_dir, "acme-budget-tracker__production.json")
    net_assess_path = os.path.join(out_assess_dir, "net-monitor__production.json")
    calc_assess_path = os.path.join(out_assess_dir, "calc-engine__production.json")

    # Check file existence
    acme_data = load_json(acme_assess_path)
    net_data = load_json(net_assess_path)
    calc_data = load_json(calc_assess_path)

    if isinstance(acme_data, dict):
        checks["file_acme_exists"] = True
    if isinstance(net_data, dict):
        checks["file_net_exists"] = True
    if isinstance(calc_data, dict):
        checks["file_calc_exists"] = True

    all_exist = checks["file_acme_exists"] and checks["file_net_exists"] and checks["file_calc_exists"]

    # Validate schemas and content only if all exist
    schema_ok = False
    policy_ok = False
    coverage_ok = False
    counts_ok = False
    statuses_ok = False
    frameworks_ok = False

    if all_exist:
        assessments = {
            "acme-budget-tracker": acme_data,
            "net-monitor": net_data,
            "calc-engine": calc_data,
        }

        # Schema validation
        def valid_assessment_schema(data: Dict[str, Any]) -> bool:
            required_fields = ["skill", "policy", "status", "assessed_at", "rules_total", "rules_passed", "rules_failed", "rules_exempted", "results"]
            for k in required_fields:
                if k not in data:
                    return False
            if not isinstance(data["skill"], str):
                return False
            if not isinstance(data["policy"], str):
                return False
            if data["status"] not in ("COMPLIANT", "NON-COMPLIANT", "EXEMPTED"):
                return False
            if not is_iso8601_utc(data["assessed_at"]):
                return False
            if not all(isinstance(data[k], int) for k in ["rules_total", "rules_passed", "rules_failed", "rules_exempted"]):
                return False
            if not isinstance(data["results"], list):
                return False
            for r in data["results"]:
                if not isinstance(r, dict):
                    return False
                for rk in ["rule", "severity", "frameworks", "passed", "exempted", "details"]:
                    if rk not in r:
                        return False
                if not isinstance(r["rule"], str):
                    return False
                if not isinstance(r["severity"], str):
                    return False
                if not isinstance(r["frameworks"], list):
                    return False
                if not isinstance(r["passed"], bool):
                    return False
                if not isinstance(r["exempted"], bool):
                    return False
                # details can be any object
            return True

        schema_ok = all(valid_assessment_schema(a) for a in assessments.values())

        # Policy field should be "production" and skill names correct
        policy_ok = (
            schema_ok and
            assessments["acme-budget-tracker"]["policy"] == "production" and
            assessments["net-monitor"]["policy"] == "production" and
            assessments["calc-engine"]["policy"] == "production" and
            assessments["acme-budget-tracker"]["skill"] == "acme-budget-tracker" and
            assessments["net-monitor"]["skill"] == "net-monitor" and
            assessments["calc-engine"]["skill"] == "calc-engine"
        )

        # Coverage: each results includes entries for every rule defined in policy
        def coverage_and_frameworks_match(data: Dict[str, Any]) -> Tuple[bool, bool]:
            res = data.get("results", [])
            names_in_results = [r.get("rule") for r in res if isinstance(r, dict)]
            names_match = set(names_in_results) == set(rule_names)
            # frameworks match
            frameworks_match = True
            for r in res:
                rn = r.get("rule")
                if rn in policy_rule_map:
                    policy_fw = policy_rule_map[rn].get("frameworks", [])
                    # Compare as exact list equality
                    if r.get("frameworks") != policy_fw:
                        frameworks_match = False
                        break
            return names_match, frameworks_match

        if schema_ok and rule_names:
            cov_ok_flags = []
            fw_ok_flags = []
            for a in assessments.values():
                cov_ok, fw_ok = coverage_and_frameworks_match(a)
                cov_ok_flags.append(cov_ok and a.get("rules_total") == len(rule_names))
                fw_ok_flags.append(fw_ok)
            coverage_ok = all(cov_ok_flags)
            frameworks_ok = all(fw_ok_flags)

        # Counts consistency: passed/exempted/failed consistency with results
        counts_ok = False
        if schema_ok:
            cflags = []
            for a in assessments.values():
                res = a["results"]
                passed = sum(1 for r in res if r.get("passed") is True)
                exempted = sum(1 for r in res if (not r.get("passed")) and r.get("exempted") is True)
                failed = sum(1 for r in res if (not r.get("passed")) and (not r.get("exempted")))
                total = len(res)
                cflags.append(
                    a["rules_total"] == total and
                    a["rules_passed"] == passed and
                    a["rules_exempted"] == exempted and
                    a["rules_failed"] == failed
                )
            counts_ok = all(cflags)

        # Statuses expected: compare to expected computed from input
        statuses_ok = False
        if schema_ok:
            sflags = []
            for name, a in assessments.items():
                exp = expected.get(name, {})
                # Compare per-rule pass/exempt and counts and status
                exp_results_by_rule = {r["rule"]: r for r in exp.get("results", [])}
                a_results_by_rule = {r["rule"]: r for r in a.get("results", [])}
                per_rule_match = True
                for rn in rule_names:
                    er = exp_results_by_rule.get(rn)
                    ar = a_results_by_rule.get(rn)
                    if er is None or ar is None:
                        per_rule_match = False
                        break
                    if (bool(er.get("passed")) != bool(ar.get("passed"))) or (bool(er.get("exempted")) != bool(ar.get("exempted"))):
                        per_rule_match = False
                        break
                counts_match = (
                    a.get("rules_total") == exp.get("rules_total") and
                    a.get("rules_passed") == exp.get("rules_passed") and
                    a.get("rules_failed") == exp.get("rules_failed") and
                    a.get("rules_exempted") == exp.get("rules_exempted")
                )
                status_match = (a.get("status") == exp.get("status"))
                sflags.append(per_rule_match and counts_match and status_match)
            statuses_ok = all(sflags)

    checks["schema_all_valid"] = schema_ok
    checks["policy_field_ok"] = policy_ok
    checks["rules_coverage_ok"] = coverage_ok
    checks["counts_consistent"] = counts_ok
    checks["statuses_expected"] = statuses_ok
    checks["frameworks_ok"] = frameworks_ok

    # Validate report.json
    report_path = os.path.join(output_dir, "report.json")
    report = load_json(report_path)
    report_valid = False
    report_totals_ok = False
    report_fw_ok = False
    if isinstance(report, dict) and all_exist and schema_ok and statuses_ok:
        # basic schema
        required_report_fields = ["policy", "policy_description", "generated_at", "total_skills", "compliant", "non_compliant", "exempted", "compliance_rate", "framework_violations", "skills"]
        report_valid = all(k in report for k in required_report_fields)
        report_valid = report_valid and report.get("policy") == "production" and is_iso8601_utc(report.get("generated_at", ""))
        report_valid = report_valid and isinstance(report.get("skills"), list) and isinstance(report.get("framework_violations"), dict)
        report_valid = report_valid and (report.get("policy_description", "") == policy_description)

        if report_valid:
            # Totals correctness
            total_skills = report.get("total_skills")
            compliant_count = report.get("compliant")
            non_compliant_count = report.get("non_compliant")
            exempted_count = report.get("exempted")
            skills_list = report.get("skills")
            report_totals_ok = (
                total_skills == 3 and
                isinstance(compliant_count, int) and
                isinstance(non_compliant_count, int) and
                isinstance(exempted_count, int) and
                isinstance(skills_list, list) and
                len(skills_list) == 3
            )
            # compute counts from expected
            exp_statuses = [expected["acme-budget-tracker"]["status"], expected["net-monitor"]["status"], expected["calc-engine"]["status"]]
            exp_compliant = exp_statuses.count("COMPLIANT")
            exp_non_compliant = exp_statuses.count("NON-COMPLIANT")
            exp_exempted = exp_statuses.count("EXEMPTED")
            report_totals_ok = report_totals_ok and (compliant_count == exp_compliant and non_compliant_count == exp_non_compliant and exempted_count == exp_exempted)

            # compliance rate tolerance
            exp_rate = ((exp_compliant + exp_exempted) / 3) * 100.0
            rep_rate = report.get("compliance_rate")
            try:
                rate_ok = abs(float(rep_rate) - float(exp_rate)) <= 0.1
            except Exception:
                rate_ok = False
            report_totals_ok = report_totals_ok and rate_ok

            # Skills array contains the three assessments (at least matching names and statuses and counts)
            skills_index = {s.get("skill"): s for s in skills_list if isinstance(s, dict) and "skill" in s}
            names_present = set(skills_index.keys()) == {"acme-budget-tracker", "net-monitor", "calc-engine"}
            if names_present:
                sk_ok_flags = []
                for name, exp_assess in expected.items():
                    s = skills_index.get(name)
                    if not s:
                        sk_ok_flags.append(False)
                        continue
                    sk_ok_flags.append(
                        s.get("policy") == "production" and
                        s.get("status") == exp_assess.get("status") and
                        s.get("rules_total") == exp_assess.get("rules_total") and
                        s.get("rules_passed") == exp_assess.get("rules_passed") and
                        s.get("rules_failed") == exp_assess.get("rules_failed") and
                        s.get("rules_exempted") == exp_assess.get("rules_exempted")
                    )
                report_totals_ok = report_totals_ok and all(sk_ok_flags)
            else:
                report_totals_ok = False

            # Framework violations: must include entries for non-exempt failures (acme's failing rules) and exclude exempted failures (net-monitor's no-network-calls)
            # Build expected non-exempt failing items
            expected_fw_map: Dict[str, List[Dict[str, Any]]] = {}
            for skill_name, exp_assess in expected.items():
                for r in exp_assess["results"]:
                    if (not r["passed"]) and (not r["exempted"]):
                        rule_name = r["rule"]
                        sev = r["severity"]
                        fws = r.get("frameworks", [])
                        for fw in fws:
                            expected_fw_map.setdefault(fw, []).append({"skill": skill_name, "rule": rule_name, "severity": sev})

            fw_map = report.get("framework_violations", {}) or {}
            # Inclusion check
            include_flags = []
            for fw, items in expected_fw_map.items():
                rep_items = fw_map.get(fw, [])
                # For each expected item, there should exist a matching item in report
                for it in items:
                    found = any(
                        isinstance(x, dict) and
                        x.get("skill") == it["skill"] and
                        x.get("rule") == it["rule"] and
                        x.get("severity") == it["severity"]
                        for x in rep_items
                    )
                    include_flags.append(found)
            include_ok = all(include_flags) if include_flags else True

            # Exclusion check for exempted failures of net-monitor's no-network-calls
            exclude_ok = True
            # find if net-monitor has exempted failures
            nm = expected["net-monitor"]
            nm_exempt_failing_rules = [r for r in nm["results"] if (not r["passed"]) and r["exempted"]]
            for r in nm_exempt_failing_rules:
                for fw in r.get("frameworks", []):
                    rep_items = fw_map.get(fw, [])
                    # ensure no entry for this skill+rule
                    for x in rep_items:
                        if isinstance(x, dict) and x.get("skill") == "net-monitor" and x.get("rule") == r["rule"]:
                            exclude_ok = False
                            break
                    if not exclude_ok:
                        break
                if not exclude_ok:
                    break

            report_fw_ok = include_ok and exclude_ok

    checks["report_valid"] = report_valid
    checks["report_totals_ok"] = report_totals_ok
    checks["report_frameworks_ok"] = report_fw_ok

    # Validate summary.txt
    summary_path = os.path.join(output_dir, "summary.txt")
    summary_text = read_file(summary_path)
    summary_ok = False
    if summary_text and all_exist and schema_ok and counts_ok and statuses_ok:
        lines = [ln.strip() for ln in summary_text.splitlines() if ln.strip()]
        # Expect exactly three lines, one for each component in any order
        if len(lines) >= 3:
            # Build expected map from assessments
            assessments_map = {
                "acme-budget-tracker": acme_data,
                "net-monitor": net_data,
                "calc-engine": calc_data,
            }
            seen = set()
            fmt_ok = True
            for ln in lines:
                # <name>: <status> — passed <n>/<total> (exempted <e>, failed <f>)
                m = re.match(r"^([a-z0-9\-]+): (COMPLIANT|NON-COMPLIANT|EXEMPTED) — passed (\d+)/(\d+) \(exempted (\d+), failed (\d+)\)$", ln, re.IGNORECASE)
                if not m:
                    # allow calc-engine hyphen; pattern includes it; regex ok
                    continue
                name = m.group(1)
                status = m.group(2)
                passed = int(m.group(3))
                total = int(m.group(4))
                exempted = int(m.group(5))
                failed = int(m.group(6))
                if name in assessments_map:
                    a = assessments_map[name]
                    fmt_ok = fmt_ok and (status == a.get("status") and passed == a.get("rules_passed") and total == a.get("rules_total") and exempted == a.get("rules_exempted") and failed == a.get("rules_failed"))
                    seen.add(name)
            summary_ok = fmt_ok and (seen == set(assessments_map.keys()))
    checks["summary_ok"] = summary_ok

    # Validate remediations.md
    rem_path = os.path.join(output_dir, "remediations.md")
    rem_text = read_file(rem_path)
    rem_ok = False
    if rem_text and all_exist and statuses_ok:
        # Identify non-exempt failing components (from expected)
        non_exempt_failing_by_skill: Dict[str, List[str]] = {}
        for skill_name, exp_assess in expected.items():
            failing_rules = [r["rule"] for r in exp_assess["results"] if (not r["passed"]) and (not r["exempted"])]
            if failing_rules:
                non_exempt_failing_by_skill[skill_name] = failing_rules

        # For each such skill, ensure there is a section containing the skill name and bullets for each failing rule
        # Consider a section if the skill name appears in a heading line (starts with '#') or anywhere; be lenient
        lines = [ln.rstrip() for ln in rem_text.splitlines()]
        skill_sections_ok = []
        for skill_name, failing_rules in non_exempt_failing_by_skill.items():
            contains_name = any((ln.strip().startswith("#") and skill_name in ln) for ln in lines) or (skill_name in rem_text)
            if not contains_name:
                skill_sections_ok.append(False)
                continue
            # For bullets referencing each rule name
            bullets_cover = True
            for rule_name in failing_rules:
                found_bullet = any((ln.strip().startswith(("-", "*")) and rule_name in ln) for ln in lines)
                if not found_bullet:
                    bullets_cover = False
                    break
            skill_sections_ok.append(contains_name and bullets_cover)
        rem_ok = all(skill_sections_ok) if skill_sections_ok else True  # If no non-exempt failures, accept; but there should be at least one (acme-budget-tracker)
    checks["remediations_ok"] = rem_ok

    # Compute reward as fraction of passed checks
    passed_checks = sum(1 for v in checks.values() if v)
    total_checks = len(checks)
    # Ensure no-op baseline: must have outputs; otherwise reward 0.0
    if not (checks["file_acme_exists"] or checks["file_net_exists"] or checks["file_calc_exists"]):
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks else 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()