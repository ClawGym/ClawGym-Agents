import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except Exception:
        # Fallback with errors ignored
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return None

def parse_context_minimal(yaml_text):
    # Minimal, line-oriented YAML reader for specific fields:
    # organization.name OR organization (string)
    # sponsor.role OR sponsor (string)
    # Returns dict with keys: org_name, sponsor_role (values or None)
    org_name = None
    sponsor_role = None

    if not yaml_text:
        return {"org_name": None, "sponsor_role": None}

    lines = yaml_text.replace("\t", "  ").splitlines()
    inside_org = False
    inside_sponsor = False
    org_indent = None
    sponsor_indent = None

    def parse_key_value(s):
        # returns (key_lower, value_stripped or None if no value)
        if ":" not in s:
            return None, None
        key, val = s.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val == "":
            return key.lower(), None
        # strip quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        return key.lower(), val

    for raw in lines:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, val = parse_key_value(raw)

        if key is None:
            # Not a simple key: value line; reset blocks if indentation decreases
            if inside_org and org_indent is not None and indent <= org_indent:
                inside_org = False
                org_indent = None
            if inside_sponsor and sponsor_indent is not None and indent <= sponsor_indent:
                inside_sponsor = False
                sponsor_indent = None
            continue

        # Handle leaving blocks when indentation decreases
        if inside_org and org_indent is not None and indent <= org_indent and key not in ("name",):
            inside_org = False
            org_indent = None
        if inside_sponsor and sponsor_indent is not None and indent <= sponsor_indent and key not in ("role",):
            inside_sponsor = False
            sponsor_indent = None

        # Organization detection
        if key == "organization":
            if val is not None and not org_name:
                org_name = val
            else:
                inside_org = True
                org_indent = indent
            continue
        if inside_org and key == "name" and val and not org_name:
            org_name = val
            continue

        # Sponsor detection
        if key == "sponsor":
            if val is not None and not sponsor_role:
                sponsor_role = val
            else:
                inside_sponsor = True
                sponsor_indent = indent
            continue
        if inside_sponsor and key == "role" and val and not sponsor_role:
            sponsor_role = val
            continue

    return {"org_name": org_name, "sponsor_role": sponsor_role}

def extract_section(content, start_marker, end_markers):
    if content is None:
        return None
    start_idx = content.find(start_marker)
    if start_idx == -1:
        return None
    end_idx = len(content)
    for em in end_markers:
        i = content.find(em, start_idx + len(start_marker))
        if i != -1:
            end_idx = min(end_idx, i)
    return content[start_idx:end_idx]

def check_plan(plan_path, context_info):
    checks = {
        "plan_exists": False,
        "plan_has_executive_summary": False,
        "plan_has_1_change_overview": False,
        "plan_has_2_stakeholder_analysis": False,
        "plan_has_adkar_table_header": False,
        "plan_has_3_communication_plan": False,
        "plan_has_4_training_enablement": False,
        "plan_has_5_resistance_mitigation": False,
        "plan_has_6_rollout_strategy": False,
        "plan_has_phase0_pilot": False,
        "plan_has_phase1_early_adopters": False,
        "plan_has_phase2_majority": False,
        "plan_has_phase3_laggards": False,
        "plan_has_go_no_go_checklist": False,
        "plan_has_checkbox_item": False,
        "plan_mentions_org_name": False,
        "plan_mentions_sponsor_role": False,
        "plan_has_healthcare_hipaa": False,
        "plan_has_healthcare_compliance_gate": False,
        "plan_has_7_success_metrics": False,
        "plan_has_8_risk_register": False,
        "plan_has_9_timeline": False,
        "timeline_mentions_week": False,
        "timeline_mentions_go_live": False,
        "plan_has_10_budget": False,
        "budget_has_training_development": False,
        "budget_has_productivity_dip": False,
        "budget_has_support_staffing": False,
        "budget_has_tools_licenses": False,
        "budget_has_communication": False,
        "budget_has_contingency": False,
        "plan_has_quick_reference_checklist": False,
        "plan_has_appendix": False,
    }
    if not os.path.isfile(plan_path):
        return checks

    checks["plan_exists"] = True
    text = read_text(plan_path) or ""
    # Headings presence
    checks["plan_has_executive_summary"] = ("Executive Summary" in text)
    checks["plan_has_1_change_overview"] = ("1. Change Overview" in text)
    checks["plan_has_2_stakeholder_analysis"] = ("2. Stakeholder Analysis" in text)
    checks["plan_has_3_communication_plan"] = ("3. Communication Plan" in text)
    checks["plan_has_4_training_enablement"] = ("4. Training & Enablement" in text)
    checks["plan_has_5_resistance_mitigation"] = ("5. Resistance Mitigation" in text)
    checks["plan_has_6_rollout_strategy"] = ("6. Rollout Strategy" in text)
    checks["plan_has_7_success_metrics"] = ("7. Success Metrics & Tracking" in text)
    checks["plan_has_8_risk_register"] = ("8. Risk Register" in text)
    checks["plan_has_9_timeline"] = ("9. Timeline & Milestones" in text)
    checks["plan_has_10_budget"] = ("10. Budget Estimate" in text)
    checks["plan_has_quick_reference_checklist"] = ("Quick-reference checklist" in text)
    checks["plan_has_appendix"] = ("Appendix" in text)

    # ADKAR header line
    adkar_header = "| Stakeholder Group | Current State | Impact Level | Likely Resistance | ADKAR Gap |"
    checks["plan_has_adkar_table_header"] = (adkar_header in text)

    # Phases — accept hyphen, en dash, or em dash
    def has_phase(label, name):
        pattern = re.compile(rf"Phase\s*{label}\s*[—–-]\s*{re.escape(name)}", re.IGNORECASE)
        return bool(pattern.search(text))
    checks["plan_has_phase0_pilot"] = has_phase("0", "Pilot")
    checks["plan_has_phase1_early_adopters"] = has_phase("1", "Early Adopters")
    checks["plan_has_phase2_majority"] = has_phase("2", "Majority")
    checks["plan_has_phase3_laggards"] = has_phase("3", "Laggards")

    # Go/No-Go Checklist and checkboxes
    checks["plan_has_go_no_go_checklist"] = ("Go/No-Go Checklist" in text)
    # Basic markdown checkbox
    checks["plan_has_checkbox_item"] = bool(re.search(r"^- \[ \]", text, flags=re.MULTILINE))

    # Organization name and sponsor role
    org_name = (context_info or {}).get("org_name")
    sponsor_role = (context_info or {}).get("sponsor_role")
    if org_name:
        checks["plan_mentions_org_name"] = (org_name in text)
    if sponsor_role:
        checks["plan_mentions_sponsor_role"] = (sponsor_role in text)

    # Healthcare compliance signals
    checks["plan_has_healthcare_hipaa"] = ("HIPAA" in text)
    checks["plan_has_healthcare_compliance_gate"] = ("compliance gate" in text or "Compliance gate" in text)

    # Timeline section checks
    timeline_section = extract_section(
        text,
        "9. Timeline & Milestones",
        ["10. Budget Estimate", "Quick-reference checklist", "Appendix"]
    )
    if timeline_section:
        checks["timeline_mentions_week"] = bool(re.search(r"\bWeek\b", timeline_section, flags=re.IGNORECASE))
        checks["timeline_mentions_go_live"] = ("Go-Live" in timeline_section)

    # Budget section checks
    budget_section = extract_section(
        text,
        "10. Budget Estimate",
        ["Quick-reference checklist", "Appendix"]
    )
    def has_budget_row(section_text, label):
        if not section_text:
            return False
        # Expect a markdown table row like: | Label | ... |
        pattern = re.compile(rf"^\s*\|\s*{re.escape(label)}\s*\|", flags=re.MULTILINE)
        return bool(pattern.search(section_text))

    checks["budget_has_training_development"] = has_budget_row(budget_section, "Training development")
    checks["budget_has_productivity_dip"] = has_budget_row(budget_section, "Productivity dip")
    checks["budget_has_support_staffing"] = has_budget_row(budget_section, "Support staffing")
    checks["budget_has_tools_licenses"] = has_budget_row(budget_section, "Tools/licenses")
    checks["budget_has_communication"] = has_budget_row(budget_section, "Communication")
    # "Contingency (15%)" label might vary slightly; accept "Contingency" prefix
    checks["budget_has_contingency"] = has_budget_row(budget_section, "Contingency") or has_budget_row(budget_section, "Contingency (15%)")

    return checks

def check_comm_calendar(csv_path):
    checks = {
        "comm_calendar_exists": False,
        "comm_calendar_header_ok": False,
        "comm_calendar_has_12_rows": False,
        "comm_audience_clinician_or_physician": False,
        "comm_audience_manager": False,
        "comm_audience_it": False,
        "comm_audience_compliance": False,
        "comm_channel_email_or_allhands_or_townhall": False,
    }
    if not os.path.isfile(csv_path):
        return checks

    checks["comm_calendar_exists"] = True

    # Validate header exactly
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            first_line = f.readline().rstrip("\n").rstrip("\r")
    except Exception:
        first_line = None

    expected_header = "week,date,audience,channel,owner,message_title"
    checks["comm_calendar_header_ok"] = (first_line == expected_header)

    # Parse with csv module
    data_rows = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip completely empty rows
                if not any((row.get(k) or "").strip() for k in row.keys()):
                    continue
                data_rows.append(row)
    except Exception:
        data_rows = []

    checks["comm_calendar_has_12_rows"] = (len(data_rows) >= 12)

    # Check audiences and channels
    for row in data_rows:
        aud = (row.get("audience") or "")
        ch = (row.get("channel") or "")
        if not checks["comm_audience_clinician_or_physician"] and re.search(r"(Clinician|Physician)", aud, re.IGNORECASE):
            checks["comm_audience_clinician_or_physician"] = True
        if not checks["comm_audience_manager"] and re.search(r"Manager", aud, re.IGNORECASE):
            checks["comm_audience_manager"] = True
        if not checks["comm_audience_it"] and re.search(r"\bIT\b", aud, re.IGNORECASE):
            checks["comm_audience_it"] = True
        if not checks["comm_audience_compliance"] and re.search(r"Compliance", aud, re.IGNORECASE):
            checks["comm_audience_compliance"] = True
        if not checks["comm_channel_email_or_allhands_or_townhall"] and (
            re.search(r"Email", ch, re.IGNORECASE) or
            re.search(r"All-hands", ch, re.IGNORECASE) or
            re.search(r"Town hall", ch, re.IGNORECASE)
        ):
            checks["comm_channel_email_or_allhands_or_townhall"] = True

    return checks

def check_metrics(metrics_path):
    checks = {
        "metrics_exists": False,
        "metrics_json_valid": False,
        "metrics_has_keys": False,
        "leading_indicators_have_name_and_target": False,
        "lagging_indicators_have_name_and_target": False,
        "cadence_has_one_key": False,
    }
    if not os.path.isfile(metrics_path):
        return checks

    checks["metrics_exists"] = True

    try:
        with open(metrics_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        checks["metrics_json_valid"] = True
    except Exception:
        return checks

    # Keys
    has_leading = isinstance(data.get("leading_indicators"), list)
    has_lagging = isinstance(data.get("lagging_indicators"), list)
    has_cadence = isinstance(data.get("tracking_cadence"), dict)
    checks["metrics_has_keys"] = bool(has_leading and has_lagging and has_cadence)

    # Validate indicators have name and target
    def items_have_fields(items):
        if not isinstance(items, list) or not items:
            return False
        for it in items:
            if not isinstance(it, dict):
                return False
            if "name" not in it or "target" not in it:
                return False
        return True

    if has_leading:
        checks["leading_indicators_have_name_and_target"] = items_have_fields(data.get("leading_indicators"))
    if has_lagging:
        checks["lagging_indicators_have_name_and_target"] = items_have_fields(data.get("lagging_indicators"))

    # Cadence keys
    cadence = data.get("tracking_cadence") if has_cadence else {}
    has_any_cadence_key = any(k in cadence for k in ("daily", "weekly", "monthly"))
    checks["cadence_has_one_key"] = bool(has_any_cadence_key)

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Load context.yaml minimally
    context_yaml_path = os.path.join(input_dir, "context.yaml")
    context_text = read_text(context_yaml_path)
    context_info = parse_context_minimal(context_text) if context_text is not None else {"org_name": None, "sponsor_role": None}

    # Paths to outputs
    plan_path = os.path.join(output_dir, "change_plan.md")
    comm_csv_path = os.path.join(output_dir, "communication_calendar.csv")
    metrics_path = os.path.join(output_dir, "metrics.json")

    # Perform checks
    plan_checks = check_plan(plan_path, context_info)
    comm_checks = check_comm_calendar(comm_csv_path)
    metrics_checks = check_metrics(metrics_path)

    # Aggregate checks
    checks = {}
    checks.update(plan_checks)
    checks.update(comm_checks)
    checks.update(metrics_checks)

    # Determine reward
    required_present = checks["plan_exists"] and checks["comm_calendar_exists"] and checks["metrics_exists"]
    # Ensure artifact-dependent checks are only True if their file exists (already enforced by functions)

    if not required_present:
        reward = 0.0
    else:
        # Average across all boolean checks
        total = 0
        passed = 0
        for k, v in checks.items():
            if isinstance(v, bool):
                total += 1
                if v:
                    passed += 1
        reward = (passed / total) if total > 0 else 0.0

    # Print exactly one JSON object on the last non-empty line
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()