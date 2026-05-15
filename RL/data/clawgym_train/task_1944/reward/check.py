import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

def read_text(path: str) -> Tuple[bool, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, ""

def read_json(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def is_numeric(value: Any) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
            return True
        except Exception:
            return False
    return False

def minimal_yaml_parse_for_dsar(content: str) -> Dict[str, Any]:
    """
    Minimal YAML-like parser for simple key: value at top level and a 'process:' block.
    Supports:
      - Top-level scalar keys with simple values (ints/strings)
      - Comments starting with '#'
      - 'process:' as a section header with indented lines below (list items or keyed subsections)
    Returns a dict with parsed top-level keys and a 'process_block' field containing the lines of the process section.
    """
    result: Dict[str, Any] = {}
    lines = content.splitlines()
    in_process = False
    process_lines: List[str] = []
    top_level_indent = None

    # Preprocess: strip BOM, normalize tabs to 2 spaces
    norm_lines = []
    for line in lines:
        if line.startswith("\ufeff"):
            line = line.lstrip("\ufeff")
        norm_lines.append(line.replace("\t", "  "))
    lines = norm_lines

    for i, raw in enumerate(lines):
        # Strip comments
        if "#" in raw:
            # Only treat as comment if not within a quoted string; simplify by splitting at ' #'
            # For our simple parser, remove from first '#' if at start or preceded by space
            idx = raw.find("#")
            if idx != -1 and (idx == 0 or raw[idx-1].isspace()):
                raw = raw[:idx]
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue

        # Determine indentation
        indent_len = len(line) - len(line.lstrip(" "))
        stripped = line.lstrip(" ")

        # Detect top-level keys (no indentation)
        if indent_len == 0:
            in_process = False  # leaving any prior section
            # key: value or key:
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip()
                if key == "process":
                    in_process = True
                    process_lines = []
                    result["process"] = True  # marker presence
                    top_level_indent = None
                    continue
                else:
                    # try to parse int for gdpr_response_days and ccpa_response_days, else keep string
                    if val == "":
                        result[key] = None
                    else:
                        # try int
                        val_cast: Any = val
                        try:
                            if re.fullmatch(r"-?\d+", val):
                                val_cast = int(val)
                            else:
                                # try float? not needed here; keep as string
                                val_cast = val
                        except Exception:
                            val_cast = val
                        result[key] = val_cast
            else:
                # Unexpected format at top-level; ignore
                continue
        else:
            # Indented lines: if currently in process block, collect lines
            if "process" in result and (in_process or top_level_indent is None):
                # Set top_level_indent for process on first indented line
                if top_level_indent is None:
                    top_level_indent = indent_len
                    in_process = True
                if in_process and indent_len >= top_level_indent:
                    process_lines.append(stripped)
                else:
                    # Dedented back to top-level
                    in_process = False

    if process_lines:
        result["process_block"] = "\n".join(process_lines)
    return result

def check_applicability(app_path: str, checks: Dict[str, bool]) -> None:
    exists = os.path.isfile(app_path)
    checks["applicability_exists"] = exists
    if not exists:
        return
    ok, data = read_json(app_path)
    checks["applicability_json_valid"] = ok and isinstance(data, dict)
    if not checks["applicability_json_valid"]:
        return
    required_regs = ["GDPR", "CCPA/CPRA", "LGPD"]
    has_regs = all(r in data for r in required_regs)
    checks["applicability_has_required_regs"] = has_regs
    triggers_ok = True
    if has_regs:
        for r in required_regs:
            val = data.get(r)
            # Accept if value is a dict that contains a non-empty string under one of common explanation keys
            if not isinstance(val, dict):
                triggers_ok = False
                break
            explanation_keys = ["trigger", "explanation", "reason", "why", "applicability_reason", "trigger_explanation"]
            found = False
            for k in explanation_keys:
                if isinstance(val.get(k), str) and val.get(k).strip():
                    found = True
                    break
            if not found:
                # Also accept a generic "applies" boolean plus a "summary" string
                if isinstance(val.get("summary"), str) and val.get("summary").strip():
                    found = True
            if not found:
                triggers_ok = False
                break
    else:
        triggers_ok = False
    checks["applicability_has_triggers_for_required"] = triggers_ok

def check_ropa(ropa_path: str, checks: Dict[str, bool]) -> None:
    exists = os.path.isfile(ropa_path)
    checks["ropa_exists"] = exists
    if not exists:
        return
    ok, data = read_json(ropa_path)
    checks["ropa_json_valid"] = ok and isinstance(data, list)
    if not checks["ropa_json_valid"]:
        return
    checks["ropa_is_array_len_ge_4"] = len(data) >= 4
    required_keys = [
        "id","name","description","controller","dpo_contact","purpose","lawful_basis",
        "data_subjects","data_categories","source","storage_location","recipients",
        "retention_period","retention_justification","deletion_method","security_measures",
        "dpia_required","owner","last_reviewed","next_review","status"
    ]
    all_have_keys = True
    has_special_or_high = False
    has_dpia_true = False
    for item in data:
        if not isinstance(item, dict):
            all_have_keys = False
            continue
        for k in required_keys:
            if k not in item:
                all_have_keys = False
                break
        # Check sensitivities
        dc = item.get("data_categories")
        if isinstance(dc, list):
            for d in dc:
                if isinstance(d, dict):
                    sens = d.get("sensitivity")
                    if isinstance(sens, str) and sens.strip().lower() in ("special","high"):
                        has_special_or_high = True
                        break
        # Check dpia_required
        if isinstance(item.get("dpia_required"), bool) and item.get("dpia_required") is True:
            has_dpia_true = True
    checks["ropa_all_items_have_required_keys"] = all_have_keys
    checks["ropa_has_special_or_high"] = has_special_or_high
    checks["ropa_has_dpia_required_true"] = has_dpia_true

def check_dpia(dpia_path: str, checks: Dict[str, bool]) -> None:
    exists = os.path.isfile(dpia_path)
    checks["dpia_exists"] = exists
    if not exists:
        return
    ok, data = read_json(dpia_path)
    checks["dpia_json_valid"] = ok and isinstance(data, dict)
    if not checks["dpia_json_valid"]:
        return
    dpia = data.get("dpia")
    has_structure = isinstance(dpia, dict) and all(
        key in dpia for key in ["id","project","date","assessor","description","necessity","risks","mitigations","decision"]
    )
    checks["dpia_has_required_structure"] = has_structure
    if not has_structure:
        checks["dpia_risks_len_ge_3"] = False
        checks["dpia_mitigations_len_ge_3"] = False
        checks["dpia_decision_residual_risk_boolean"] = False
        return
    risks = dpia.get("risks")
    mitigations = dpia.get("mitigations")
    decision = dpia.get("decision")
    checks["dpia_risks_len_ge_3"] = isinstance(risks, list) and len(risks) >= 3
    checks["dpia_mitigations_len_ge_3"] = isinstance(mitigations, list) and len(mitigations) >= 3
    rra = None
    if isinstance(decision, dict):
        rra = decision.get("residual_risk_acceptable")
    checks["dpia_decision_residual_risk_boolean"] = isinstance(rra, bool)

def check_dsar(dsar_path: str, checks: Dict[str, bool]) -> None:
    exists = os.path.isfile(dsar_path)
    checks["dsar_exists"] = exists
    if not exists:
        return
    ok, text = read_text(dsar_path)
    if not ok:
        checks["dsar_yaml_parsed"] = False
        checks["dsar_gdpr_30"] = False
        checks["dsar_ccpa_45"] = False
        checks["dsar_process_has_steps"] = False
        return
    parsed = minimal_yaml_parse_for_dsar(text)
    # If we didn't get anything, parsed is empty dict
    # Consider parsed if we can extract the required integers and process
    dsar_yaml_parsed = isinstance(parsed, dict) and len(parsed) > 0
    checks["dsar_yaml_parsed"] = dsar_yaml_parsed

    gdpr_days = parsed.get("gdpr_response_days")
    ccpa_days = parsed.get("ccpa_response_days")
    checks["dsar_gdpr_30"] = isinstance(gdpr_days, int) and gdpr_days == 30
    checks["dsar_ccpa_45"] = isinstance(ccpa_days, int) and ccpa_days == 45

    # Process steps
    steps_required = ["receive","verify","scope","search","review","respond","close"]
    process_block = parsed.get("process_block", "")
    # If no process_block, try searching entire file
    source_to_search = process_block if process_block else text
    found_all = True
    low = source_to_search.lower()
    for s in steps_required:
        if s not in low:
            found_all = False
            break
    checks["dsar_process_has_steps"] = found_all

def check_vendor_assessments(vendor_path: str, checks: Dict[str, bool]) -> None:
    exists = os.path.isfile(vendor_path)
    checks["vendor_exists"] = exists
    if not exists:
        return
    ok, data = read_json(vendor_path)
    checks["vendor_json_valid"] = ok and isinstance(data, list)
    if not checks["vendor_json_valid"]:
        return
    checks["vendor_len_ge_2"] = len(data) >= 2
    required_fields = ["vendor","service","data_types","assessment_date","scores","decision","review_frequency"]
    score_fields = ["security_posture","data_handling","contractual_terms","breach_history","sub_processor_mgmt","cross_border","reputation","total"]
    allowed_decisions = {"Approve", "Approve with conditions", "Reject"}

    all_have_fields = True
    all_scores_numeric = True
    decisions_allowed = True
    for item in data:
        if not isinstance(item, dict):
            all_have_fields = False
            all_scores_numeric = False
            decisions_allowed = False
            break
        for k in required_fields:
            if k not in item:
                all_have_fields = False
                break
        scores = item.get("scores")
        if not isinstance(scores, dict):
            all_scores_numeric = False
        else:
            for sk in score_fields:
                if sk not in scores or not is_numeric(scores.get(sk)):
                    all_scores_numeric = False
                    break
        decision = item.get("decision")
        if decision not in allowed_decisions:
            decisions_allowed = False
    checks["vendor_each_has_required_fields"] = all_have_fields
    checks["vendor_scores_fields_numeric"] = all_scores_numeric
    checks["vendor_decisions_allowed"] = decisions_allowed

def check_breach_register(br_path: str, checks: Dict[str, bool]) -> None:
    exists = os.path.isfile(br_path)
    checks["breach_register_exists"] = exists
    if not exists:
        return
    ok, data = read_json(br_path)
    checks["breach_register_json_valid"] = ok and isinstance(data, list)
    if not checks["breach_register_json_valid"]:
        return
    checks["breach_register_array_nonempty"] = len(data) >= 1
    required = ["id","date_detected","date_contained","nature","cause","data_subjects_affected","records_affected","data_categories","risk_level","authority_notified","subjects_notified","root_cause","remediation","lessons_learned"]
    has_required = True
    for item in data:
        if not isinstance(item, dict):
            has_required = False
            break
        for k in required:
            if k not in item:
                has_required = False
                break
        # Optional type checks for booleans
        if has_required:
            an = item.get("authority_notified")
            sn = item.get("subjects_notified")
            if not isinstance(an, bool) or not isinstance(sn, bool):
                has_required = False
                break
    checks["breach_register_has_required_fields"] = has_required

def check_breach_playbook(bp_path: str, checks: Dict[str, bool]) -> None:
    exists = os.path.isfile(bp_path)
    checks["breach_playbook_exists"] = exists
    if not exists:
        return
    ok, text = read_text(bp_path)
    if not ok:
        checks["breach_playbook_has_72h"] = False
        checks["breach_playbook_has_detection_containment"] = False
        checks["breach_playbook_has_notification"] = False
        return
    low = text.lower()
    # Check for "72h" or "72 hours"
    has_72h = bool(re.search(r"72\s*(hours?|h)\b", low))
    checks["breach_playbook_has_72h"] = has_72h
    # Detection/containment presence
    det_cont = ("detect" in low or "detection" in low) and ("contain" in low or "containment" in low)
    checks["breach_playbook_has_detection_containment"] = det_cont
    # Notification mention
    notif = ("notification" in low) or ("notify" in low)
    checks["breach_playbook_has_notification"] = notif

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # Paths for expected outputs
    app_path = os.path.join(output_dir, "applicability.json")
    ropa_path = os.path.join(output_dir, "ropa.json")
    dpia_path = os.path.join(output_dir, "dpia.json")
    dsar_path = os.path.join(output_dir, "dsar_workflow.yaml")
    vendor_path = os.path.join(output_dir, "vendor_assessments.json")
    br_path = os.path.join(output_dir, "breach_register.json")
    bp_path = os.path.join(output_dir, "breach_playbook.md")

    # Initialize all checks False
    initial_keys = [
        "applicability_exists","applicability_json_valid","applicability_has_required_regs","applicability_has_triggers_for_required",
        "ropa_exists","ropa_json_valid","ropa_is_array_len_ge_4","ropa_all_items_have_required_keys","ropa_has_special_or_high","ropa_has_dpia_required_true",
        "dpia_exists","dpia_json_valid","dpia_has_required_structure","dpia_risks_len_ge_3","dpia_mitigations_len_ge_3","dpia_decision_residual_risk_boolean",
        "dsar_exists","dsar_yaml_parsed","dsar_gdpr_30","dsar_ccpa_45","dsar_process_has_steps",
        "vendor_exists","vendor_json_valid","vendor_len_ge_2","vendor_each_has_required_fields","vendor_scores_fields_numeric","vendor_decisions_allowed",
        "breach_register_exists","breach_register_json_valid","breach_register_array_nonempty","breach_register_has_required_fields",
        "breach_playbook_exists","breach_playbook_has_72h","breach_playbook_has_detection_containment","breach_playbook_has_notification"
    ]
    for k in initial_keys:
        checks[k] = False

    # Perform checks
    check_applicability(app_path, checks)
    check_ropa(ropa_path, checks)
    check_dpia(dpia_path, checks)
    check_dsar(dsar_path, checks)
    check_vendor_assessments(vendor_path, checks)
    check_breach_register(br_path, checks)
    check_breach_playbook(bp_path, checks)

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # No-op baseline: if output dir missing or empty and no checks passed, reward remains 0.0
    # Clamp reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    # Print final JSON with reward first, then checks
    result = {"reward": reward}
    for k, v in checks.items():
        result[k] = v
    print(json.dumps(result))

if __name__ == "__main__":
    main()