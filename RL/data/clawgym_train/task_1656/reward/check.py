import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_simple_yaml(yaml_text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in yaml_text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1] if stack else root
        if content.endswith(":"):
            key = content[:-1].strip()
            new_dict: Dict[str, Any] = {}
            current[key] = new_dict
            stack.append((indent, new_dict))
        else:
            if ":" not in content:
                continue
            key, value = content.split(":", 1)
            key = key.strip()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            lv = value.lower()
            if lv in ("true", "false"):
                parsed_value: Any = lv == "true"
            else:
                try:
                    parsed_value = int(value)
                except ValueError:
                    parsed_value = value
            current[key] = parsed_value
    return root


def parse_requirements_text(text: str) -> Dict[str, str]:
    pkgs: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        name = name.strip()
        version = version.strip()
        pkgs[name] = version
    return pkgs


def load_vuln_db(text: str) -> Dict[str, Dict[str, List[dict]]]:
    data = json.loads(text)
    norm: Dict[str, Dict[str, List[dict]]] = {}
    for pkg, versions in data.items():
        norm[pkg.lower()] = {}
        for ver, vulns in versions.items():
            norm[pkg.lower()][ver] = vulns
    return norm


def compute_expected_depscan_report(reqs: Dict[str, str], db: Dict[str, Dict[str, List[dict]]]) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    packages_with_vulns = set()
    for pkg, ver in reqs.items():
        vulns_for_pkg = db.get(pkg.lower(), {})
        vulns_for_ver = vulns_for_pkg.get(ver, [])
        for v in vulns_for_ver:
            findings.append({
                "package": pkg,
                "version": ver,
                "cve_id": v.get("id"),
                "severity": v.get("severity"),
                "fixed_in": v.get("fixed_in"),
            })
            packages_with_vulns.add(pkg)
    report = {
        "summary": {
            "total_packages": len(reqs),
            "packages_with_vulns": len(packages_with_vulns),
            "total_findings": len(findings),
        },
        "findings": findings,
        "requirements": reqs,
    }
    return report


def get_markdown_section(md_text: str, heading: str) -> Optional[str]:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(md_text)
    if not match:
        return None
    start = match.end()
    next_heading = re.compile(r"^##\s+.+$", re.MULTILINE)
    next_match = next_heading.search(md_text, start)
    end = next_match.start() if next_match else len(md_text)
    return md_text[start:end]


def find_line_containing(text: str, substring: str) -> Optional[str]:
    for line in text.splitlines():
        if substring in line:
            return line
    return None


def scan_jsonl_pii(log_text: str) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[str], Optional[str], bool]:
    total = 0
    email_count = 0
    phone_count = 0
    ts_email: Optional[str] = None
    ts_phone: Optional[str] = None
    email_re = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
    phone_re = re.compile(r"\+1-\d{3}-\d{3}-\d{4}")
    for line in log_text.splitlines():
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            obj = json.loads(line)
        except Exception:
            return None, None, None, None, None, False
        q = str(obj.get("query", ""))
        has_email = email_re.search(q) is not None
        has_phone = phone_re.search(q) is not None
        if has_email:
            email_count += 1
            if ts_email is None:
                ts_email = str(obj.get("ts"))
        if has_phone:
            phone_count += 1
            if ts_phone is None:
                ts_phone = str(obj.get("ts"))
    return total, email_count, phone_count, ts_email, ts_phone, True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "depscan_report_exists_and_valid": 0.0,
        "depscan_report_matches_expected": 0.0,
        "risk_report_has_required_sections": 0.0,
        "risk_report_config_values_present": 0.0,
        "risk_report_config_risks_marked": 0.0,
        "risk_report_dep_summary_counts_correct": 0.0,
        "risk_report_dep_findings_listed": 0.0,
        "risk_report_log_counts_correct": 0.0,
        "risk_report_log_example_ts_present": 0.0,
        "risk_report_no_raw_pii": 0.0,
        "security_policy_logging_section_updated": 0.0,
        "security_policy_deps_section_lists_cves_and_actions": 0.0,
    }

    depscan_report_path = workspace / "workspace" / "depscan_report.json"
    risk_report_path = workspace / "workspace" / "security_risk_report.md"
    config_yaml_path = workspace / "input" / "config" / "search_config.yaml"
    logs_jsonl_path = workspace / "input" / "logs" / "query_log.jsonl"
    reqs_path = workspace / "input" / "requirements.txt"
    vuln_db_path = workspace / "input" / "vulnerabilities.json"
    policy_path = workspace / "docs" / "security_policy.md"

    expected_report: Optional[Dict[str, Any]] = None
    reqs_text = safe_read_text(reqs_path)
    vuln_text = safe_read_text(vuln_db_path)
    if reqs_text is not None and vuln_text is not None:
        try:
            reqs = parse_requirements_text(reqs_text)
            db = load_vuln_db(vuln_text)
            expected_report = compute_expected_depscan_report(reqs, db)
        except Exception:
            expected_report = None

    report_json = safe_load_json(depscan_report_path)
    if isinstance(report_json, dict) and "summary" in report_json and "findings" in report_json and "requirements" in report_json:
        scores["depscan_report_exists_and_valid"] = 1.0

    if expected_report is not None and isinstance(report_json, dict):
        try:
            exp_sum = expected_report.get("summary", {})
            rep_sum = report_json.get("summary", {})
            sum_ok = (
                rep_sum.get("total_packages") == exp_sum.get("total_packages")
                and rep_sum.get("packages_with_vulns") == exp_sum.get("packages_with_vulns")
                and rep_sum.get("total_findings") == exp_sum.get("total_findings")
            )
            reqs_ok = report_json.get("requirements") == expected_report.get("requirements")
            exp_findings = expected_report.get("findings", [])
            rep_findings = report_json.get("findings", [])
            def norm(f: Dict[str, Any]) -> Tuple[Any, Any, Any, Any, Any]:
                return (f.get("package"), f.get("version"), f.get("cve_id"), f.get("severity"), f.get("fixed_in"))
            findings_ok = {norm(f) for f in exp_findings} == {norm(f) for f in rep_findings}
            if sum_ok and reqs_ok and findings_ok:
                scores["depscan_report_matches_expected"] = 1.0
        except Exception:
            pass

    risk_text = safe_read_text(risk_report_path)
    if risk_text is not None:
        has_sections = all((
            re.search(r"Configuration\s+Risks", risk_text, re.IGNORECASE) is not None,
            re.search(r"Dependency\s+Vulnerabilities", risk_text, re.IGNORECASE) is not None,
            re.search(r"Log\s+PII\s+Findings", risk_text, re.IGNORECASE) is not None
        ))
        if has_sections:
            scores["risk_report_has_required_sections"] = 1.0

        config_text = safe_read_text(config_yaml_path)
        if config_text is not None:
            cfg = parse_simple_yaml(config_text)
            expected_fields = {
                "logging.store_queries": str(cfg.get("logging", {}).get("store_queries")).lower(),
                "logging.anonymize_queries": str(cfg.get("logging", {}).get("anonymize_queries")).lower(),
                "logging.redact_pii": str(cfg.get("logging", {}).get("redact_pii")).lower(),
                "storage.retain_raw_docs_days": str(cfg.get("storage", {}).get("retain_raw_docs_days")),
                "telemetry.send_usage_telemetry": str(cfg.get("telemetry", {}).get("send_usage_telemetry")).lower(),
            }
            present_ok = True
            for field, val in expected_fields.items():
                token = f"{field}: {val}"
                if token not in risk_text:
                    present_ok = False
                    break
            if present_ok:
                scores["risk_report_config_values_present"] = 1.0

            # Determine risk per field based on stated criteria
            store_queries = cfg.get("logging", {}).get("store_queries")
            anonymize_queries = cfg.get("logging", {}).get("anonymize_queries")
            redact_pii = cfg.get("logging", {}).get("redact_pii")
            retain_days = cfg.get("storage", {}).get("retain_raw_docs_days")
            send_telemetry = cfg.get("telemetry", {}).get("send_usage_telemetry")
            combo_risky = bool(store_queries) and (not bool(anonymize_queries) or not bool(redact_pii))
            risk_by_field: Dict[str, bool] = {
                "logging.store_queries": combo_risky,
                "logging.anonymize_queries": combo_risky,
                "logging.redact_pii": combo_risky,
                "storage.retain_raw_docs_days": isinstance(retain_days, int) and retain_days > 90,
                "telemetry.send_usage_telemetry": bool(send_telemetry),
            }
            risky_ok = True
            for field, val in expected_fields.items():
                token = f"{field}: {val}"
                line = find_line_containing(risk_text, token)
                if not line:
                    risky_ok = False
                    break
                expected_has_risky = risk_by_field.get(field, False)
                has_risky_word = re.search(r"\brisky\b", line, re.IGNORECASE) is not None
                # Require "risky" when expected risky; require absence otherwise
                if expected_has_risky and not has_risky_word:
                    risky_ok = False
                    break
                if not expected_has_risky and has_risky_word:
                    risky_ok = False
                    break
            if risky_ok:
                scores["risk_report_config_risks_marked"] = 1.0

        if isinstance(report_json, dict):
            total_pkgs = report_json.get("summary", {}).get("total_packages")
            pkgs_with_vulns = report_json.get("summary", {}).get("packages_with_vulns")
            if isinstance(total_pkgs, int) and isinstance(pkgs_with_vulns, int):
                m_total = re.search(r"total[^.\n]*packages[^0-9]*([0-9]+)", risk_text, re.IGNORECASE)
                m_vuln = re.search(r"packages[^.\n]*with[^.\n]*vulnerab[^0-9]*([0-9]+)", risk_text, re.IGNORECASE)
                if m_total and m_vuln:
                    try:
                        total_val = int(m_total.group(1))
                        vuln_val = int(m_vuln.group(1))
                        if total_val == total_pkgs and vuln_val == pkgs_with_vulns:
                            scores["risk_report_dep_summary_counts_correct"] = 1.0
                    except Exception:
                        pass
            findings_listed_ok = True
            for f in report_json.get("findings", []):
                line = f"{f.get('package')} {f.get('version')} -> {f.get('cve_id')} ({f.get('severity')}), fixed in {f.get('fixed_in')}"
                if line not in risk_text:
                    findings_listed_ok = False
                    break
            if report_json.get("findings"):
                if findings_listed_ok:
                    scores["risk_report_dep_findings_listed"] = 1.0
            else:
                scores["risk_report_dep_findings_listed"] = 1.0

        logs_text = safe_read_text(logs_jsonl_path)
        if logs_text is not None and risk_text is not None:
            total, email_count, phone_count, ts_email, ts_phone, parse_ok = scan_jsonl_pii(logs_text)
            if parse_ok and total is not None and email_count is not None and phone_count is not None:
                m_total_lines = re.search(r"total[^.\n]*lines[^.\n]*scanned[^0-9]*([0-9]+)", risk_text, re.IGNORECASE)
                m_email = re.search(r"email(?:\s+address)?[^.\n]*([0-9]+)", risk_text, re.IGNORECASE)
                m_phone = re.search(r"phone(?:\s+number|s)?[^.\n]*([0-9]+)", risk_text, re.IGNORECASE)
                try:
                    if m_total_lines and int(m_total_lines.group(1)) == total and \
                       m_email and int(m_email.group(1)) == email_count and \
                       m_phone and int(m_phone.group(1)) == phone_count:
                        scores["risk_report_log_counts_correct"] = 1.0
                except Exception:
                    pass
                ts_ok = True
                if ts_email:
                    if ts_email not in risk_text:
                        ts_ok = False
                if ts_phone:
                    if ts_phone not in risk_text:
                        ts_ok = False
                if ts_ok and ts_email is not None and ts_phone is not None:
                    scores["risk_report_log_example_ts_present"] = 1.0
                pii_absent = ("john.doe@example.com" not in risk_text) and ("+1-555-123-4567" not in risk_text)
                if pii_absent:
                    scores["risk_report_no_raw_pii"] = 1.0

    policy_text = safe_read_text(policy_path)
    if policy_text is not None:
        logging_section = get_markdown_section(policy_text, "Logging")
        if logging_section is not None:
            has_anonymize_queries = re.search(r"anonymize\s+queries", logging_section, re.IGNORECASE) is not None
            has_redact_pii = re.search(r"redact\s+pii", logging_section, re.IGNORECASE) is not None
            has_limit_30 = re.search(r"limit\s+retention\s+to\s+30\s+days", logging_section, re.IGNORECASE) is not None
            has_no_raw_queries_statement = (
                re.search(r"raw\s+queries", logging_section, re.IGNORECASE) is not None and
                re.search(r"must\s+not", logging_section, re.IGNORECASE) is not None and
                re.search(r"anonymization", logging_section, re.IGNORECASE) is not None and
                re.search(r"redaction", logging_section, re.IGNORECASE) is not None
            )
            if has_anonymize_queries and has_redact_pii and has_limit_30 and has_no_raw_queries_statement:
                scores["security_policy_logging_section_updated"] = 1.0

        deps_section = get_markdown_section(policy_text, "Third-party Dependencies")
        deps_ok = False
        if deps_section is not None and isinstance(report_json, dict):
            cves_ok = True
            packages_ok = True
            expected_cves: List[str] = []
            expected_pkgs: List[str] = []
            for f in report_json.get("findings", []):
                cve = f.get("cve_id")
                pkg = f.get("package")
                if cve:
                    expected_cves.append(cve)
                if pkg:
                    expected_pkgs.append(pkg)
            expected_cves = list(dict.fromkeys(expected_cves))
            expected_pkgs = list(dict.fromkeys(expected_pkgs))
            for cve in expected_cves:
                if cve not in deps_section:
                    cves_ok = False
                    break
            for pkg in expected_pkgs:
                if re.search(rf"\b{re.escape(pkg)}\b", deps_section, re.IGNORECASE) is None:
                    packages_ok = False
                    break
            actions_ok = (
                re.search(r"\bpin\w*\b", deps_section, re.IGNORECASE) is not None and
                re.search(r"\bupgrade\w*\b", deps_section, re.IGNORECASE) is not None and
                re.search(r"\bfixed\b", deps_section, re.IGNORECASE) is not None
            )
            deps_ok = cves_ok and packages_ok and actions_ok
        if deps_ok:
            scores["security_policy_deps_section_lists_cves_and_actions"] = 1.0

    return scores


def main() -> None:
    workspace_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_arg)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()