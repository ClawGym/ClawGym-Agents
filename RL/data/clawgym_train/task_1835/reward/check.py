import json
import os
import sys
from typing import Any, Dict, List, Optional

def load_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def to_int(val) -> Optional[int]:
    try:
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, str):
            s = val.strip()
            if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
                return int(s)
        return None
    except Exception:
        return None

def find_entries_array(obj: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(obj, dict):
        return None
    # Primary expected key
    for key in ["entries", "items", "audits", "controls", "plan", "schedule"]:
        arr = obj.get(key)
        if isinstance(arr, list):
            return arr
    return None

def find_entry_by_control(entries: List[Dict[str, Any]], control_code: str) -> Optional[Dict[str, Any]]:
    for e in entries:
        if isinstance(e, dict):
            c = e.get("control")
            if isinstance(c, str) and c.strip() == control_code:
                return e
    return None

def risk_to_expected_freq(risk: str) -> Optional[int]:
    mapping = {
        "critical": 4,
        "high": 2,
        "medium": 1,
        "low": 1,
    }
    if not isinstance(risk, str):
        return None
    r = risk.strip().lower()
    return mapping.get(r)

def has_all_fields(entry: Dict[str, Any], fields: List[str]) -> bool:
    return all(field in entry for field in fields)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        # audit_plan.json
        "audit_json_exists": False,
        "audit_json_valid": False,
        "audit_year_2026": False,
        "audit_has_entries_array": False,
        "audit_has_A82": False,
        "audit_has_A88": False,
        "audit_has_A51": False,
        "audit_fields_A82": False,
        "audit_fields_A88": False,
        "audit_fields_A51": False,
        "audit_freq_map_A82": False,
        "audit_freq_map_A88": False,
        "audit_freq_map_A51": False,
        # audit_plan.md
        "audit_md_exists": False,
        "audit_md_has_headings": False,
        # control_test_plans.md
        "test_plans_exists": False,
        "test_plans_has_controls": False,
        "test_plans_has_methods": False,
        "test_plans_has_sampling": False,
        # findings.json
        "findings_exists": False,
        "findings_valid_json": False,
        "findings_is_array": False,
        "findings_at_least_3": False,
        "findings_has_major_30": False,
        "findings_has_minor_90": False,
        "findings_has_observation_0": False,
        "findings_all_have_control_reference": False,
        # corrective_actions.md
        "corrective_actions_exists": False,
        "corrective_actions_has_fields": False,
        # certification_checklist.md
        "checklist_exists": False,
        "checklist_has_stages": False,
        "checklist_has_3months_phrase": False,
    }

    # Paths
    audit_json_path = os.path.join(output_dir, "audit_plan.json")
    audit_md_path = os.path.join(output_dir, "audit_plan.md")
    test_plans_path = os.path.join(output_dir, "control_test_plans.md")
    findings_json_path = os.path.join(output_dir, "findings.json")
    corrective_actions_path = os.path.join(output_dir, "corrective_actions.md")
    checklist_path = os.path.join(output_dir, "certification_checklist.md")

    # 1) audit_plan.json
    if os.path.isfile(audit_json_path):
        checks["audit_json_exists"] = True
        audit_obj = load_json(audit_json_path)
        if audit_obj is not None and isinstance(audit_obj, dict):
            checks["audit_json_valid"] = True
            if audit_obj.get("year") == 2026:
                checks["audit_year_2026"] = True
            entries = find_entries_array(audit_obj)
            if isinstance(entries, list):
                checks["audit_has_entries_array"] = True
                # required controls
                for code, has_key, fields_key, freq_key in [
                    ("A.8.2", "audit_has_A82", "audit_fields_A82", "audit_freq_map_A82"),
                    ("A.8.8", "audit_has_A88", "audit_fields_A88", "audit_freq_map_A88"),
                    ("A.5.1", "audit_has_A51", "audit_fields_A51", "audit_freq_map_A51"),
                ]:
                    entry = find_entry_by_control(entries, code)
                    if entry is not None:
                        checks[has_key] = True
                        # fields presence
                        required_fields = ["control", "name", "risk", "frequency_per_year"]
                        if has_all_fields(entry, required_fields):
                            checks[fields_key] = True
                            # frequency mapping check
                            expected_freq = risk_to_expected_freq(entry.get("risk"))
                            freq_val = to_int(entry.get("frequency_per_year"))
                            if expected_freq is not None and freq_val is not None and freq_val == expected_freq:
                                checks[freq_key] = True

    # 2) audit_plan.md
    if os.path.isfile(audit_md_path):
        checks["audit_md_exists"] = True
        txt = load_text(audit_md_path)
        if isinstance(txt, str):
            low = txt.lower()
            if ("audit plan" in low) and ("auditor independence" in low):
                checks["audit_md_has_headings"] = True

    # 3) control_test_plans.md
    if os.path.isfile(test_plans_path):
        checks["test_plans_exists"] = True
        ttxt = load_text(test_plans_path) or ""
        low = ttxt.lower()
        # controls references exact strings should appear
        has_controls = ("a.8.2" in ttxt) and ("a.8.8" in ttxt)
        checks["test_plans_has_controls"] = has_controls
        # four method keywords
        methods_ok = all(k in low for k in ["inquiry", "observation", "inspection", "re-performance"])
        checks["test_plans_has_methods"] = methods_ok
        if "sampling" in low:
            checks["test_plans_has_sampling"] = True

    # 4) findings.json
    if os.path.isfile(findings_json_path):
        checks["findings_exists"] = True
        fj = load_json(findings_json_path)
        if fj is not None:
            checks["findings_valid_json"] = True
            if isinstance(fj, list):
                checks["findings_is_array"] = True
                if len(fj) >= 3:
                    checks["findings_at_least_3"] = True
                # Severity/SLAs
                major_ok = False
                minor_ok = False
                obs_ok = False
                all_have_control_ref = True
                for item in fj if isinstance(fj, list) else []:
                    if not isinstance(item, dict):
                        continue
                    # control_reference field check
                    if "control_reference" not in item:
                        all_have_control_ref = False
                    # severity + SLA checks
                    sev = item.get("severity")
                    sla = to_int(item.get("response_sla_days"))
                    if isinstance(sev, str):
                        s = sev.strip()
                        if s.lower() == "major" and sla == 30:
                            major_ok = True
                        if s.lower() == "minor" and sla == 90:
                            minor_ok = True
                        if s.lower() == "observation" and sla == 0:
                            obs_ok = True
                if major_ok:
                    checks["findings_has_major_30"] = True
                if minor_ok:
                    checks["findings_has_minor_90"] = True
                if obs_ok:
                    checks["findings_has_observation_0"] = True
                if all_have_control_ref and isinstance(fj, list) and len(fj) > 0:
                    checks["findings_all_have_control_reference"] = True

    # 5) corrective_actions.md
    if os.path.isfile(corrective_actions_path):
        checks["corrective_actions_exists"] = True
        ctxt = load_text(corrective_actions_path) or ""
        low = ctxt.lower()
        if ("root cause" in low) and ("corrective action" in low) and ("target date" in low):
            checks["corrective_actions_has_fields"] = True

    # 6) certification_checklist.md
    if os.path.isfile(checklist_path):
        checks["checklist_exists"] = True
        ch = load_text(checklist_path) or ""
        low = ch.lower()
        # Stages
        if ("stage 1" in low) and ("stage 2" in low):
            checks["checklist_has_stages"] = True
        # exact phrase, case-sensitive as specified
        if "ISMS operational for minimum 3 months" in ch:
            checks["checklist_has_3months_phrase"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline already results in 0.0 since no checks pass; ensure float bounds
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()