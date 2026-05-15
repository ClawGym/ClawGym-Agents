import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "policy_exists": False,
        "policy_matches": False,
        "audit_exists": False,
        "audit_valid_json": False,
        "audit_has_required_findings": False,
        "audit_counts_match": False,
        "audit_totals_match": False,
        "summary_exists": False,
        "summary_contains_required": False,
    }

    # Expected policy structure
    expected_policy = {
        "version": 1,
        "name": "default",
        "rules": {
            "commands": {
                "allow": ["git", "python3", "node", "npm", "pip"],
                "block": ["curl|bash", "wget -O-|sh", "rm -rf /", "chmod 777"],
                "review": ["sudo", "docker", "ssh"],
            },
            "network": {
                "allow_domains": ["github.com", "pypi.org", "npmjs.com"],
                "block_domains": ["pastebin.com", "transfer.sh", "ngrok.io"],
                "block_patterns": ["*.tk", "*.ml", "*.ga"],
            },
            "data_handling": {
                "pii_scan": True,
                "secret_scan": True,
                "log_retention_days": 90,
            },
            "workspace": {
                "require_gitignore": True,
                "require_audit_trail": False,
                "require_skill_signing": False,
                "max_skill_risk_score": 50,
            },
        },
    }

    # Paths
    policy_path = os.path.join(output_dir, ".marshal-policy.json")
    audit_path = os.path.join(output_dir, "audit.json")
    summary_path = os.path.join(output_dir, "summary.md")

    # Check policy
    if os.path.isfile(policy_path):
        checks["policy_exists"] = True
        policy_json = load_json(policy_path)
        if policy_json is not None and policy_json == expected_policy:
            checks["policy_matches"] = True

    # Check audit.json
    audit_json = None
    if os.path.isfile(audit_path):
        checks["audit_exists"] = True
        audit_json = load_json(audit_path)
        if isinstance(audit_json, dict):
            checks["audit_valid_json"] = True

    # Verify audit findings and counts/totals if audit is valid
    if checks["audit_valid_json"]:
        # Required minimal findings: tuples (rule, severity, file, line)
        required_findings = [
            ("commands.pipe_to_shell", "CRITICAL", "skills/evil-skill/evil.py", 3),
            ("network.block_domains", "CRITICAL", "skills/evil-skill/evil.py", 3),
            ("commands.chmod_777", "CRITICAL", "skills/evil-skill/evil.py", 4),
            ("commands.rm_rf_root", "CRITICAL", "skills/evil-skill/evil.py", 6),
            ("network.block_domains", "CRITICAL", "skills/net-skill/net.py", 2),
            ("network.block_patterns", "HIGH", "skills/net-skill/net.py", 3),
            ("network.allow_domains", "INFO", "skills/net-skill/net.py", 4),
            ("data_handling.secret_scan", "HIGH", ".marshal-policy.json", 0),
            ("data_handling.pii_scan", "MEDIUM", ".marshal-policy.json", 0),
            ("workspace.require_gitignore", "MEDIUM", ".gitignore", 0),
            ("config.debug_mode", "LOW", "skills/alpha-skill/alpha.py", 1),
            ("config.debug_print", "LOW", "skills/alpha-skill/alpha.py", 2),
        ]

        findings = audit_json.get("findings")
        if isinstance(findings, list):
            # Build a set of tuples for quick lookup
            present = set()
            for item in findings:
                try:
                    rule = item.get("rule")
                    sev = item.get("severity")
                    file = item.get("file")
                    line = item.get("line")
                    if isinstance(rule, str) and isinstance(sev, str) and isinstance(file, str) and isinstance(line, int):
                        present.add((rule, sev, file, line))
                except Exception:
                    continue
            if all(req in present for req in required_findings):
                checks["audit_has_required_findings"] = True

        # Counts
        expected_counts = {"CRITICAL": 5, "HIGH": 2, "MEDIUM": 2, "LOW": 2, "INFO": 1}
        counts = audit_json.get("counts")
        if isinstance(counts, dict):
            # Check exact match for the five severities
            severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
            if all(counts.get(sev) == expected_counts[sev] for sev in severities) and len(counts) == len(severities):
                checks["audit_counts_match"] = True

        # Totals and grading
        expected_total_deductions = 178
        expected_score = 0
        expected_grade = "F"
        expected_exit_code = 2
        td = audit_json.get("total_deductions")
        sc = audit_json.get("score")
        gr = audit_json.get("grade")
        ec = audit_json.get("exit_code")
        if td == expected_total_deductions and sc == expected_score and gr == expected_grade and ec == expected_exit_code:
            checks["audit_totals_match"] = True

    # Check summary.md
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        text = read_text(summary_path) or ""
        required_snippets = [
            "CRITICAL: 5",
            "HIGH: 2",
            "MEDIUM: 2",
            "LOW: 2",
            "INFO: 1",
            "Score: 0",
            "Grade: F",
            "Exit code: 2",
        ]
        if all(snippet in text for snippet in required_snippets):
            checks["summary_contains_required"] = True

    # Compute reward: fraction of checks passed; enforce no-op baseline 0.0
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    # No-op baseline: if output dir missing or no required artifacts, reward must be 0.0
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        # If none of the primary artifacts exist, zero
        primary_any = checks["policy_exists"] or checks["audit_exists"] or checks["summary_exists"]
        if not primary_any:
            reward = 0.0
        else:
            reward = passed_checks / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()