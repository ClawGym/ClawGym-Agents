import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def first_nonempty_line(lines, start=0):
    for i in range(start, len(lines)):
        if lines[i].strip() != "":
            return i
    return None

def has_section_list_nonempty(yaml_text, section_name):
    # Check that a YAML section contains at least one list item "- ..."
    lines = yaml_text.splitlines()
    section_idx = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(section_name)}\s*:\s*$", line):
            section_idx = i
            break
    if section_idx is None:
        return False
    # Scan following lines until a new top-level or same-indent key appears
    base_indent = len(lines[section_idx]) - len(lines[section_idx].lstrip(" "))
    found_item = False
    for j in range(section_idx + 1, len(lines)):
        ln = lines[j]
        if ln.strip() == "":
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        # if indentation is <= base_indent and looks like another key, stop
        if indent <= base_indent and re.match(r"^[A-Za-z0-9_\-]+\s*:", ln.strip()):
            break
        # look for list item
        if re.match(r"^\s*-\s+.+", ln):
            found_item = True
            break
    return found_item

def extract_block_after_key(yaml_text, key_name):
    # Return the indented block text after a given key line
    lines = yaml_text.splitlines()
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(key_name)}\s*:\s*$", line):
            base_indent = len(line) - len(line.lstrip(" "))
            block_lines = []
            for j in range(i + 1, len(lines)):
                ln = lines[j]
                # stop if indentation <= base_indent and looks like a new key
                if ln.strip() == "":
                    block_lines.append(ln)
                    continue
                indent = len(ln) - len(ln.lstrip(" "))
                if indent <= base_indent and re.match(r"^[A-Za-z0-9_\-]+\s*:", ln.strip()):
                    break
                if indent > base_indent:
                    block_lines.append(ln)
                else:
                    break
            return "\n".join(block_lines)
    return ""

def find_int_value_in_block(block_text, key):
    # Find "key: <int>"
    m = re.search(rf"^\s*{re.escape(key)}\s*:\s*([0-9]+)\s*$", block_text, flags=re.MULTILINE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def csv_read_first_two_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = [row for row in reader]
        # get first two non-empty rows
        nonempty = [r for r in rows if any(cell.strip() != "" for cell in r)]
        if len(nonempty) >= 2:
            return nonempty[0], nonempty[1], True
        elif len(nonempty) == 1:
            return nonempty[0], None, True
        else:
            return None, None, True
    except Exception:
        return None, None, False

def count_words(text):
    return len(re.findall(r"\b\w+\b", text))

def str_contains_all(text, phrases):
    if text is None:
        return False
    for p in phrases:
        if p not in text:
            return False
    return True

def is_number(val):
    return isinstance(val, (int, float)) and not isinstance(val, bool)

def is_int_number(val):
    return isinstance(val, int) and not isinstance(val, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    voice_agent_dir = os.path.join(output_dir, "voice_agent")
    diary_dir = os.path.join(output_dir, "diary")

    # Initialize checks
    checks = {}

    # File paths
    platform_path = os.path.join(voice_agent_dir, "platform_decision.json")
    conversation_path = os.path.join(voice_agent_dir, "conversation.yaml")
    system_prompt_path = os.path.join(voice_agent_dir, "system_prompt.txt")
    compliance_path = os.path.join(voice_agent_dir, "compliance_checklist.yaml")
    test_suite_path = os.path.join(voice_agent_dir, "test_suite.yaml")
    monitoring_path = os.path.join(voice_agent_dir, "monitoring_dashboard.json")
    roi_path = os.path.join(voice_agent_dir, "roi.csv")
    quality_rubric_path = os.path.join(voice_agent_dir, "quality_rubric.json")
    runbook_path = os.path.join(voice_agent_dir, "runbook.md")
    diary_reflection_path = os.path.join(diary_dir, "agent_reflection.md")

    # Existence checks
    checks["exists_platform_decision_json"] = os.path.isfile(platform_path)
    checks["exists_conversation_yaml"] = os.path.isfile(conversation_path)
    checks["exists_system_prompt_txt"] = os.path.isfile(system_prompt_path)
    checks["exists_compliance_checklist_yaml"] = os.path.isfile(compliance_path)
    checks["exists_test_suite_yaml"] = os.path.isfile(test_suite_path)
    checks["exists_monitoring_dashboard_json"] = os.path.isfile(monitoring_path)
    checks["exists_roi_csv"] = os.path.isfile(roi_path)
    checks["exists_quality_rubric_json"] = os.path.isfile(quality_rubric_path)
    checks["exists_runbook_md"] = os.path.isfile(runbook_path)
    checks["exists_diary_agent_reflection_md"] = os.path.isfile(diary_reflection_path)

    # 2) platform_decision.json validations
    checks["platform_json_parseable"] = False
    checks["platform_chosen_nonempty"] = False
    checks["platform_alternatives_array"] = False
    checks["platform_latency_le_1500"] = False
    checks["platform_tooling_stack_keys"] = False
    if checks["exists_platform_decision_json"]:
        pdata, ok = parse_json_file(platform_path)
        checks["platform_json_parseable"] = ok
        if ok and isinstance(pdata, dict):
            cp = pdata.get("chosen_platform")
            checks["platform_chosen_nonempty"] = isinstance(cp, str) and len(cp.strip()) > 0
            alts = pdata.get("alternatives")
            checks["platform_alternatives_array"] = isinstance(alts, list)
            lat = pdata.get("latency_target_ms")
            checks["platform_latency_le_1500"] = is_number(lat) and lat <= 1500
            ts = pdata.get("tooling_stack")
            ts_ok = isinstance(ts, dict)
            for key in ["stt", "llm", "tts", "telephony"]:
                ts_ok = ts_ok and isinstance(ts.get(key), str) and len(ts.get(key).strip()) > 0
            checks["platform_tooling_stack_keys"] = ts_ok

    # 3) conversation.yaml validations (string-based YAML checks)
    checks["conversation_has_opening_greeting"] = False
    checks["conversation_has_closing_goodbye"] = False
    checks["conversation_primary_intents_include_appointment_and_billing"] = False
    checks["conversation_has_fallback_intent"] = False
    checks["conversation_has_barge_in_min_speech_ms_int"] = False
    checks["conversation_has_timeout_turn"] = False
    if checks["exists_conversation_yaml"]:
        ctext = read_text(conversation_path) or ""
        # Require conversation_flow, opening, greeting tokens
        has_conv = "conversation_flow:" in ctext
        checks["conversation_has_opening_greeting"] = has_conv and ("opening:" in ctext) and (re.search(r"\bgreeting\s*:\s*.+", ctext) is not None)
        # closing.goodbye
        checks["conversation_has_closing_goodbye"] = has_conv and ("closing:" in ctext) and (re.search(r"\bgoodbye\s*:\s*.+", ctext) is not None)
        # primary intents include appointment_booking and billing_inquiry via "intent:" entries
        intents_found = set(re.findall(r"intent\s*:\s*([A-Za-z0-9_\-]+)", ctext))
        checks["conversation_primary_intents_include_appointment_and_billing"] = ("appointment_booking" in intents_found and "billing_inquiry" in intents_found)
        # fallback_intent presence
        checks["conversation_has_fallback_intent"] = ("fallback_intent" in ctext)
        # barge_in_detection.min_speech_ms integer > 0
        block = extract_block_after_key(ctext, "interruption_strategy")
        bid_block = extract_block_after_key(block, "barge_in_detection") if block else ""
        min_ms = find_int_value_in_block(bid_block, "min_speech_ms")
        checks["conversation_has_barge_in_min_speech_ms_int"] = isinstance(min_ms, int) and min_ms > 0
        # timeout presence
        has_timeout_seconds = re.search(r"\btimeout_seconds\s*:\s*[0-9]+", ctext) is not None
        has_timeout_response = re.search(r"\btimeout_response\s*:\s*.+", ctext) is not None
        checks["conversation_has_timeout_turn"] = has_timeout_seconds and has_timeout_response

    # 4) system_prompt.txt
    checks["system_prompt_has_brevity_rule"] = False
    checks["system_prompt_has_one_question_rule"] = False
    checks["system_prompt_has_never_process_card_numbers"] = False
    checks["system_prompt_mentions_medical_emergency"] = False
    if checks["exists_system_prompt_txt"]:
        sp_text = read_text(system_prompt_path) or ""
        checks["system_prompt_has_brevity_rule"] = ("Keep ALL responses under 2 sentences (30 words max)" in sp_text)
        checks["system_prompt_has_one_question_rule"] = ("Ask ONE question at a time" in sp_text)
        checks["system_prompt_has_never_process_card_numbers"] = ("Never process card numbers" in sp_text)
        checks["system_prompt_mentions_medical_emergency"] = ("medical emergency" in sp_text)

    # 5) compliance_checklist.yaml
    checks["compliance_yaml_has_top_keys"] = False
    checks["compliance_pci_has_secure_ivr_redirect"] = False
    if checks["exists_compliance_checklist_yaml"]:
        comp_text = read_text(compliance_path) or ""
        top_keys = all(k + ":" in comp_text for k in ["tcpa", "state_laws", "gdpr", "pci_dss", "hipaa"])
        checks["compliance_yaml_has_top_keys"] = top_keys
        # Find pci_dss block and method within
        pci_block = extract_block_after_key(comp_text, "pci_dss")
        ph_block = extract_block_after_key(pci_block, "payment_handling") if pci_block else ""
        method_ok = re.search(r"^\s*method\s*:\s*secure_ivr_redirect\s*$", ph_block, flags=re.MULTILINE) is not None
        checks["compliance_pci_has_secure_ivr_redirect"] = method_ok

    # 6) test_suite.yaml
    checks["test_suite_has_happy_paths"] = False
    checks["test_suite_has_edge_cases"] = False
    checks["test_suite_has_error_paths"] = False
    checks["test_suite_has_escalation_paths"] = False
    checks["test_suite_has_adversarial"] = False
    checks["test_suite_has_compliance"] = False
    if checks["exists_test_suite_yaml"]:
        ts_text = read_text(test_suite_path) or ""
        checks["test_suite_has_happy_paths"] = has_section_list_nonempty(ts_text, "happy_paths")
        checks["test_suite_has_edge_cases"] = has_section_list_nonempty(ts_text, "edge_cases")
        checks["test_suite_has_error_paths"] = has_section_list_nonempty(ts_text, "error_paths")
        checks["test_suite_has_escalation_paths"] = has_section_list_nonempty(ts_text, "escalation_paths")
        checks["test_suite_has_adversarial"] = has_section_list_nonempty(ts_text, "adversarial")
        checks["test_suite_has_compliance"] = has_section_list_nonempty(ts_text, "compliance")

    # 7) monitoring_dashboard.json
    checks["monitoring_json_parseable"] = False
    checks["monitoring_real_time_numeric_fields"] = False
    checks["monitoring_has_response_latency_alert_rule"] = False
    if checks["exists_monitoring_dashboard_json"]:
        mdata, mok = parse_json_file(monitoring_path)
        checks["monitoring_json_parseable"] = mok
        if mok and isinstance(mdata, dict):
            dashboard = mdata.get("dashboard")
            rt_ok = False
            if isinstance(dashboard, dict):
                rt = dashboard.get("real_time")
                if isinstance(rt, dict):
                    needed = ["active_calls", "avg_latency_ms", "error_rate_percent", "queue_depth"]
                    rt_ok = all(is_number(rt.get(k)) for k in needed)
            checks["monitoring_real_time_numeric_fields"] = bool(rt_ok)
            # alert rules
            a_ok = False
            alert_rules = dashboard.get("alert_rules") if isinstance(dashboard, dict) else None
            if isinstance(alert_rules, list):
                for rule in alert_rules:
                    if isinstance(rule, dict) and rule.get("metric") == "Response latency":
                        w = rule.get("warning")
                        c = rule.get("critical")
                        if is_number(w) and is_number(c):
                            a_ok = True
                            break
            checks["monitoring_has_response_latency_alert_rule"] = a_ok

    # 8) roi.csv
    checks["roi_csv_header_ok"] = False
    checks["roi_csv_first_row_positive_numbers"] = False
    checks["roi_csv_ai_less_than_human"] = False
    checks["roi_csv_monthly_savings_positive"] = False
    if checks["exists_roi_csv"]:
        header, row1, ok = csv_read_first_two_rows(roi_path)
        if ok and header is not None:
            header_exact = header == ["ai_cost_per_call", "human_cost_per_call", "calls_per_day", "monthly_savings"]
            checks["roi_csv_header_ok"] = header_exact
            if row1 is not None and len(row1) >= 4:
                try:
                    ai = float(row1[0])
                    human = float(row1[1])
                    calls = float(row1[2])
                    savings = float(row1[3])
                    checks["roi_csv_first_row_positive_numbers"] = (ai > 0 and human > 0 and calls > 0 and savings > 0)
                    checks["roi_csv_ai_less_than_human"] = (ai < human)
                    checks["roi_csv_monthly_savings_positive"] = (savings > 0)
                except Exception:
                    pass

    # 9) quality_rubric.json
    checks["quality_rubric_json_parseable"] = False
    checks["quality_rubric_has_required_keys"] = False
    checks["quality_rubric_weights_integers"] = False
    checks["quality_rubric_weights_sum_100"] = False
    if checks["exists_quality_rubric_json"]:
        qdata, qok = parse_json_file(quality_rubric_path)
        checks["quality_rubric_json_parseable"] = qok
        required_keys = [
            "conversation_accuracy",
            "response_latency",
            "voice_naturalness",
            "error_handling",
            "compliance_adherence",
            "integration_reliability",
            "user_satisfaction",
        ]
        if qok and isinstance(qdata, dict):
            has_keys = all(k in qdata for k in required_keys)
            checks["quality_rubric_has_required_keys"] = has_keys
            if has_keys:
                ints = all(is_int_number(qdata.get(k)) for k in required_keys)
                checks["quality_rubric_weights_integers"] = ints
                total = sum(int(qdata.get(k)) for k in required_keys)
                checks["quality_rubric_weights_sum_100"] = (total == 100)

    # 10) runbook.md
    checks["runbook_has_required_headings"] = False
    checks["runbook_has_self_documentation_phrase"] = False
    if checks["exists_runbook_md"]:
        rb = read_text(runbook_path) or ""
        needed_headings = [
            "Your Role",
            "Blocking Check",
            "Input",
            "Process",
            "Output",
            "Quality Checklist",
            "Common Issues",
        ]
        checks["runbook_has_required_headings"] = all(h in rb for h in needed_headings)
        checks["runbook_has_self_documentation_phrase"] = ("Self-Documentation" in rb)

    # 11) diary/agent_reflection.md
    checks["diary_word_count_400_600"] = False
    checks["diary_has_summary"] = False
    checks["diary_has_wins"] = False
    checks["diary_has_frustrations"] = False
    checks["diary_has_learnings"] = False
    checks["diary_has_tomorrows_focus"] = False
    if checks["exists_diary_agent_reflection_md"]:
        dtext = read_text(diary_reflection_path) or ""
        wc = count_words(dtext)
        checks["diary_word_count_400_600"] = (wc >= 400 and wc <= 600)
        checks["diary_has_summary"] = ("Summary" in dtext)
        checks["diary_has_wins"] = ("Wins" in dtext)
        checks["diary_has_frustrations"] = ("Frustrations" in dtext)
        checks["diary_has_learnings"] = ("Learnings" in dtext)
        checks["diary_has_tomorrows_focus"] = ("Tomorrow's Focus" in dtext)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Enforce no-op baseline: if no output dir or all artifact files missing, reward must be 0.0
    artifact_exists = any([
        checks["exists_platform_decision_json"],
        checks["exists_conversation_yaml"],
        checks["exists_system_prompt_txt"],
        checks["exists_compliance_checklist_yaml"],
        checks["exists_test_suite_yaml"],
        checks["exists_monitoring_dashboard_json"],
        checks["exists_roi_csv"],
        checks["exists_quality_rubric_json"],
        checks["exists_runbook_md"],
        checks["exists_diary_agent_reflection_md"],
    ])
    if not artifact_exists:
        reward = 0.0

    # Print result JSON (single line)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()