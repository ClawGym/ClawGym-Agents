import json
import os
import re
import sys
from typing import Any, Dict, List

def load_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def looks_like_iso8601(s: str) -> bool:
    # Simple shape check: YYYY-MM-DDT...
    return isinstance(s, str) and re.match(r"^\d{4}-\d{2}-\d{2}T", s) is not None

def is_bool(x: Any) -> bool:
    return isinstance(x, bool)

def check_report(report_path: str) -> Dict[str, bool]:
    checks = {
        "report_exists": False,
        "report_contains_system_health_score": False,
        "report_contains_executive_summary": False,
        "report_contains_security_audit_findings": False,
        "report_contains_update_status": False,
        "report_contains_firewall_status": False,
        "report_contains_open_ports": False,
        "report_contains_system_vitals": False,
        "report_contains_recommendations_section": False,
        "report_contains_severity_tag": False,
        "report_recommendations_have_bullets": False,
    }
    if not os.path.isfile(report_path):
        return checks

    checks["report_exists"] = True
    content = load_text(report_path)

    # Required literal section labels
    if "System Health Score" in content:
        checks["report_contains_system_health_score"] = True
    if "Executive Summary" in content:
        checks["report_contains_executive_summary"] = True
    if "Security Audit Findings" in content:
        checks["report_contains_security_audit_findings"] = True
    if "Update Status" in content:
        checks["report_contains_update_status"] = True
    if "Firewall Status" in content:
        checks["report_contains_firewall_status"] = True
    if "Open Ports" in content:
        checks["report_contains_open_ports"] = True
    if "System Vitals" in content:
        checks["report_contains_system_vitals"] = True

    # Recommendations section/heading presence (case-insensitive accept)
    if re.search(r"\bRecommendations\b", content, flags=re.IGNORECASE):
        checks["report_contains_recommendations_section"] = True

        # Look for bullet points following the first occurrence of "Recommendations"
        # Accept lines starting with "- " or "* "
        lines = content.splitlines()
        rec_index = None
        for idx, line in enumerate(lines):
            if re.search(r"\bRecommendations\b", line, flags=re.IGNORECASE):
                rec_index = idx
                break
        if rec_index is not None:
            # Scan next ~100 lines for bullets
            end_idx = min(len(lines), rec_index + 100)
            for j in range(rec_index + 1, end_idx):
                l = lines[j].lstrip()
                if l.startswith("- ") or l.startswith("* "):
                    checks["report_recommendations_have_bullets"] = True
                    break

    # At least one severity tag [low], [medium], [high], or [critical]
    if re.search(r"\[(low|medium|high|critical)\]", content, flags=re.IGNORECASE):
        checks["report_contains_severity_tag"] = True

    return checks

def check_json_summary(json_path: str) -> Dict[str, bool]:
    checks = {
        "summary_exists": False,
        "summary_valid_json": False,
        "json_systemHealthScore_valid": False,
        "json_auditFindings_valid": False,
        "json_updates_valid": False,
        "json_firewall_valid": False,
        "json_openPorts_valid": False,
        "json_os_valid": False,
        "json_generatedAt_valid": False,
    }
    if not os.path.isfile(json_path):
        return checks

    checks["summary_exists"] = True

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        checks["summary_valid_json"] = True
    except Exception:
        return checks

    # systemHealthScore: number 0–100 inclusive
    shs = data.get("systemHealthScore", None)
    if isinstance(shs, (int, float)) and not isinstance(shs, bool) and 0 <= shs <= 100:
        checks["json_systemHealthScore_valid"] = True

    # auditFindings: array of objects with id, title, severity, category
    af_valid = False
    af = data.get("auditFindings", None)
    if isinstance(af, list):
        af_valid = True
        for item in af:
            if not isinstance(item, dict):
                af_valid = False
                break
            if not isinstance(item.get("id"), str):
                af_valid = False
                break
            if not isinstance(item.get("title"), str):
                af_valid = False
                break
            sev = item.get("severity")
            if sev not in ("low", "medium", "high", "critical"):
                af_valid = False
                break
            if not isinstance(item.get("category"), str):
                af_valid = False
                break
    checks["json_auditFindings_valid"] = af_valid

    # updates: { outdated: boolean, outdatedCount: number }
    upd = data.get("updates", None)
    upd_valid = False
    if isinstance(upd, dict):
        outdated = upd.get("outdated", None)
        outdated_count = upd.get("outdatedCount", None)
        if isinstance(outdated, bool) and isinstance(outdated_count, (int, float)) and not isinstance(outdated_count, bool):
            upd_valid = True
    checks["json_updates_valid"] = upd_valid

    # firewall: { active: boolean, tool: string }
    fw = data.get("firewall", None)
    fw_valid = False
    if isinstance(fw, dict):
        active = fw.get("active", None)
        tool = fw.get("tool", None)
        if isinstance(active, bool) and isinstance(tool, str):
            fw_valid = True
    checks["json_firewall_valid"] = fw_valid

    # openPorts: number[]
    ports = data.get("openPorts", None)
    ports_valid = False
    if isinstance(ports, list):
        ok = True
        for p in ports:
            if not (isinstance(p, int) and not isinstance(p, bool)):
                ok = False
                break
        if ok:
            ports_valid = True
    checks["json_openPorts_valid"] = ports_valid

    # os: { name: string, version: string }
    os_obj = data.get("os", None)
    os_valid = False
    if isinstance(os_obj, dict):
        if isinstance(os_obj.get("name"), str) and isinstance(os_obj.get("version"), str):
            os_valid = True
    checks["json_os_valid"] = os_valid

    # generatedAt: ISO 8601-like
    ga = data.get("generatedAt", None)
    checks["json_generatedAt_valid"] = looks_like_iso8601(ga)

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")
    report_path = os.path.join(output_dir, "healthcheck", "system_health_report.md")
    summary_path = os.path.join(output_dir, "healthcheck", "system_health_summary.json")

    checks_report = check_report(report_path)
    checks_json = check_json_summary(summary_path)

    # Aggregate checks
    checks: Dict[str, bool] = {}
    checks.update(checks_report)
    checks.update(checks_json)

    # Ensure no-op baseline: If output directory missing or both required artifacts missing → reward 0.0
    # Otherwise, compute proportion of passed checks.
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # Reward computation:
    # If neither file exists, or output dir missing, reward = 0.0.
    if not os.path.isdir(output_dir) or (not checks_report["report_exists"] and not checks_json["summary_exists"]):
        reward = 0.0
    else:
        # Deterministic proportional scoring across all checks
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    # Add checks
    result.update(checks)

    print(json.dumps(result))

if __name__ == "__main__":
    main()