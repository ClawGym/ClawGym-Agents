import json
import os
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    report_path = os.path.join(output_dir, "security_report.json")
    summary_path = os.path.join(output_dir, "summary.txt")

    checks = {
        "report_exists": False,
        "report_valid_json": False,
        "has_required_fields": False,
        "skill_name_correct": False,
        "findings_array": False,
        "valid_severities": False,
        "total_count_correct": False,
        "by_severity_counts_correct": False,
        "verdict_correct": False,
        "required_prompt_injection_finding": False,
        "required_shell_true_finding": False,
        "required_serialized_code_loading_finding": False,
        "required_posts_exfil_finding": False,
        "required_env_vars_finding": False,
        "required_non_https_finding": False,
        "file_paths_relative": False,
        "summary_exists": False,
        "summary_nonempty": False,
    }

    data = None

    # Check existence of report
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        # Load JSON
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            checks["report_valid_json"] = True
        except Exception:
            data = None

    # Structure checks
    allowed_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    if data and isinstance(data, dict):
        required_top_keys = {"skill", "total_findings", "findings", "by_severity", "verdict"}
        if required_top_keys.issubset(data.keys()):
            # Type validations
            skill_ok = isinstance(data.get("skill"), str)
            total_ok = isinstance(data.get("total_findings"), int)
            findings_ok = isinstance(data.get("findings"), list)
            bysev_ok = isinstance(data.get("by_severity"), dict)
            verdict_ok = isinstance(data.get("verdict"), str)
            if skill_ok and total_ok and findings_ok and bysev_ok and verdict_ok:
                checks["has_required_fields"] = True

            # Skill name exact
            if skill_ok and data.get("skill") == "skill_to_review":
                checks["skill_name_correct"] = True

            # Findings array and entries validation
            if findings_ok:
                findings = data.get("findings", [])
                # Validate each finding structure and types
                per_finding_types_ok = True
                severities_all_valid = True
                file_paths_rel_ok = True
                for item in findings:
                    if not isinstance(item, dict):
                        per_finding_types_ok = False
                        break
                    if not isinstance(item.get("file"), str):
                        per_finding_types_ok = False
                        break
                    if not isinstance(item.get("line"), int):
                        per_finding_types_ok = False
                        break
                    if not isinstance(item.get("severity"), str) or item.get("severity") not in allowed_severities:
                        per_finding_types_ok = False
                        severities_all_valid = False
                        break
                    if not isinstance(item.get("description"), str):
                        per_finding_types_ok = False
                        break
                    if "match" not in item or not isinstance(item.get("match"), str):
                        per_finding_types_ok = False
                        break
                    # File path should be relative (not start with /)
                    file_field = item.get("file", "")
                    if file_field.startswith("/"):
                        file_paths_rel_ok = False
                if per_finding_types_ok:
                    checks["findings_array"] = True
                if severities_all_valid and per_finding_types_ok:
                    checks["valid_severities"] = True
                if file_paths_rel_ok and per_finding_types_ok:
                    checks["file_paths_relative"] = True

                # total_findings equals len(findings)
                if isinstance(data.get("total_findings"), int) and len(findings) == data.get("total_findings"):
                    checks["total_count_correct"] = True

                # by_severity counts
                bysev = data.get("by_severity", {})
                bysev_keys_ok = set(bysev.keys()) == allowed_severities or allowed_severities.issubset(bysev.keys())
                bysev_types_ok = all(isinstance(bysev.get(k), int) for k in allowed_severities if k in bysev)
                # Compute actual counts from findings
                actual_counts = {k: 0 for k in allowed_severities}
                for item in findings:
                    sev = item.get("severity")
                    if sev in actual_counts:
                        actual_counts[sev] += 1
                counts_match = False
                if bysev_keys_ok and bysev_types_ok:
                    # Allow "by_severity" to have exactly the four keys; ignore extras if present but require at least the four
                    counts_match = all(bysev.get(k) == actual_counts[k] for k in allowed_severities)
                if counts_match:
                    checks["by_severity_counts_correct"] = True

                # Verdict rule check
                verdict = data.get("verdict")
                expected_verdict = "CLEAN"
                if actual_counts["CRITICAL"] > 0:
                    expected_verdict = "CRITICAL"
                elif actual_counts["HIGH"] > 0:
                    expected_verdict = "HIGH"
                elif sum(actual_counts.values()) > 0:
                    expected_verdict = "MEDIUM"
                if verdict == expected_verdict:
                    checks["verdict_correct"] = True

                # Required findings presence
                # 1) SKILL.md Prompt injection override instructions, CRITICAL
                for item in findings:
                    if (
                        item.get("file") == "SKILL.md"
                        and item.get("description") == "Prompt injection: override instructions"
                        and item.get("severity") == "CRITICAL"
                        and isinstance(item.get("line"), int)
                    ):
                        checks["required_prompt_injection_finding"] = True
                        break

                # 2) scripts/suspicious.py Shell=True in subprocess — RCE risk, HIGH
                for item in findings:
                    if (
                        item.get("file") == "scripts/suspicious.py"
                        and item.get("description") == "Shell=True in subprocess — RCE risk"
                        and item.get("severity") == "HIGH"
                        and isinstance(item.get("line"), int)
                    ):
                        checks["required_shell_true_finding"] = True
                        break

                # 3) scripts/suspicious.py Serialized code loading, CRITICAL
                for item in findings:
                    if (
                        item.get("file") == "scripts/suspicious.py"
                        and item.get("description") == "Serialized code loading"
                        and item.get("severity") == "CRITICAL"
                        and isinstance(item.get("line"), int)
                    ):
                        checks["required_serialized_code_loading_finding"] = True
                        break

                # 4) scripts/suspicious.py POSTs data externally, HIGH
                for item in findings:
                    if (
                        item.get("file") == "scripts/suspicious.py"
                        and item.get("description") == "POSTs data externally"
                        and item.get("severity") == "HIGH"
                        and isinstance(item.get("line"), int)
                    ):
                        checks["required_posts_exfil_finding"] = True
                        break

                # 5) scripts/suspicious.py Reads sensitive env vars, MEDIUM
                for item in findings:
                    if (
                        item.get("file") == "scripts/suspicious.py"
                        and item.get("description") == "Reads sensitive env vars"
                        and item.get("severity") == "MEDIUM"
                        and isinstance(item.get("line"), int)
                    ):
                        checks["required_env_vars_finding"] = True
                        break

                # 6) At least one Non-HTTPS URL found, LOW (file can be SKILL.md or scripts/suspicious.py)
                for item in findings:
                    if (
                        item.get("description") == "Non-HTTPS URL found"
                        and item.get("severity") == "LOW"
                        and isinstance(item.get("line"), int)
                    ):
                        # Optionally check file is one of the two scanned targets
                        # but allow any file as long as relative
                        checks["required_non_https_finding"] = True
                        break

    # Summary file checks
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()
            if isinstance(content, str) and len(content.strip()) > 0:
                checks["summary_nonempty"] = True
        except Exception:
            pass

    # Compute reward
    # No-op baseline: if report missing or output dir empty, reward = 0.0
    if not checks["report_exists"]:
        reward = 0.0
    else:
        # Fraction of checks passed
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Ensure reward within [0,1]
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print final JSON (single line, reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()