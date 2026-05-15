import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def lower(s):
    return s.lower() if isinstance(s, str) else ""

def contains_any(text, substrings):
    t = lower(text)
    return any(sub in t for sub in [s.lower() for s in substrings])

def contains_all(text, substrings):
    t = lower(text)
    return all(sub in t for sub in [s.lower() for s in substrings])

def last_non_empty_print(obj):
    # Ensure exactly one JSON object on the last non-empty line
    s = json.dumps(obj)
    print(s)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    diagnosis_path = os.path.join(output_dir, "diagnosis.md")
    fix_plan_path = os.path.join(output_dir, "fix_plan.json")
    updated_code_path = os.path.join(output_dir, "updated_code.txt")

    # -----------------------------
    # Diagnosis checks (file + content)
    # -----------------------------
    checks["has_diagnosis"] = os.path.isfile(diagnosis_path)
    diag_text = read_text(diagnosis_path) if checks["has_diagnosis"] else None

    # Initialize all diagnosis-related checks to False
    checks["diagnosis_common_ground"] = False
    checks["diagnosis_external_supply_servo_5v"] = False
    checks["diagnosis_level_shifter_3v_5v"] = False
    checks["diagnosis_current_limiting_resistor"] = False
    checks["diagnosis_input_pullup"] = False
    checks["diagnosis_pins01_serial_conflict"] = False
    checks["diagnosis_baud_rate"] = False
    checks["diagnosis_decoupling_or_0_1uf"] = False
    checks["diagnosis_millis_nonblocking_with_delay"] = False

    if checks["has_diagnosis"] and isinstance(diag_text, str):
        # common ground
        if contains_all(diag_text, ["common ground"]):
            checks["diagnosis_common_ground"] = True
        # external supply + servo/motor + 5V
        if (contains_any(diag_text, ["external supply", "separate supply"])
            and contains_any(diag_text, ["servo", "motor"])
            and contains_any(diag_text, ["5V", "5v"])):
            checks["diagnosis_external_supply_servo_5v"] = True
        # level shifter or logic level AND 3.3V and 5V
        if (contains_any(diag_text, ["level shifter", "logic level"])
            and contains_any(diag_text, ["3.3V", "3.3 v", "3.3v"])
            and contains_any(diag_text, ["5V", "5 v", "5v"])):
            checks["diagnosis_level_shifter_3v_5v"] = True
        # current-limiting resistor
        if contains_all(diag_text, ["current-limiting resistor"]):
            checks["diagnosis_current_limiting_resistor"] = True
        # INPUT_PULLUP
        if contains_all(diag_text, ["input_pullup"]):
            checks["diagnosis_input_pullup"] = True
        # pins 0/1 or RX/TX AND serial conflict or serial monitor
        if (contains_any(diag_text, ["pins 0/1", "rx/tx"])
            and contains_any(diag_text, ["serial conflict", "serial monitor"])):
            checks["diagnosis_pins01_serial_conflict"] = True
        # baud rate
        if contains_all(diag_text, ["baud rate"]):
            checks["diagnosis_baud_rate"] = True
        # decoupling or 0.1uF
        if contains_any(diag_text, ["decoupling", "0.1uf"]):
            checks["diagnosis_decoupling_or_0_1uf"] = True
        # millis() or non-blocking AND mention of delay
        if (contains_any(diag_text, ["millis()", "non-blocking"])
            and contains_any(diag_text, ["delay"])):
            checks["diagnosis_millis_nonblocking_with_delay"] = True

    # -----------------------------
    # Fix plan checks
    # -----------------------------
    checks["has_fix_plan"] = os.path.isfile(fix_plan_path)
    checks["fix_plan_valid_json_array"] = False
    checks["fix_plan_len_ge_8"] = False
    checks["fix_plan_elements_have_keys"] = False
    checks["fix_plan_categories_cover_all"] = False
    checks["fix_plan_severities_allowed"] = False

    # Phrase coverage in actions/rationales
    checks["fix_plan_phrase_common_ground"] = False
    checks["fix_plan_phrase_external_supply_servo_motor"] = False
    checks["fix_plan_phrase_level_shifter_3v_5v"] = False
    checks["fix_plan_phrase_current_limiting_resistor"] = False
    checks["fix_plan_phrase_input_pullup"] = False
    checks["fix_plan_phrase_pins01_or_rx_tx"] = False
    checks["fix_plan_phrase_millis"] = False
    checks["fix_plan_phrase_baud_rate"] = False

    if checks["has_fix_plan"]:
        text = read_text(fix_plan_path)
        if isinstance(text, str):
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    checks["fix_plan_valid_json_array"] = True
                    if len(data) >= 8:
                        checks["fix_plan_len_ge_8"] = True
                    # validate keys presence per element
                    required_keys = {"id", "category", "severity", "action", "rationale", "references"}
                    elements_have_keys = True
                    categories = set()
                    severities = set()
                    # Collect actions+rationales for phrase checks
                    combined = []
                    for item in data:
                        if not isinstance(item, dict):
                            elements_have_keys = False
                            break
                        if not required_keys.issubset(item.keys()):
                            elements_have_keys = False
                            break
                        # accumulate sets
                        cat = item.get("category")
                        sev = item.get("severity")
                        if isinstance(cat, str):
                            categories.add(cat)
                        if isinstance(sev, str):
                            severities.add(sev)
                        act = item.get("action", "")
                        rat = item.get("rationale", "")
                        if isinstance(act, str):
                            combined.append(act)
                        if isinstance(rat, str):
                            combined.append(rat)
                    if elements_have_keys:
                        checks["fix_plan_elements_have_keys"] = True

                    # categories cover: Power, Wiring, Code, Communication, Debugging
                    required_categories = {"Power", "Wiring", "Code", "Communication", "Debugging"}
                    if required_categories.issubset(categories):
                        checks["fix_plan_categories_cover_all"] = True

                    # severities allowed only within allowed set
                    allowed_severities = {"critical", "high", "medium", "low"}
                    if all((isinstance(s, str) and s in allowed_severities) for s in severities):
                        checks["fix_plan_severities_allowed"] = True

                    # Phrase checks across actions/rationales
                    combined_text = " \n".join(combined)
                    # common ground
                    if contains_any(combined_text, ["common ground"]):
                        checks["fix_plan_phrase_common_ground"] = True
                    # external supply/separate supply + servo/motor
                    if (contains_any(combined_text, ["external supply", "separate supply"])
                        and contains_any(combined_text, ["servo", "motor"])):
                        checks["fix_plan_phrase_external_supply_servo_motor"] = True
                    # level shifter or logic level + 3.3V + 5V
                    if (contains_any(combined_text, ["level shifter", "logic level"])
                        and contains_any(combined_text, ["3.3v", "3.3 v"])
                        and contains_any(combined_text, ["5v", "5 v"])):
                        checks["fix_plan_phrase_level_shifter_3v_5v"] = True
                    # current-limiting resistor
                    if contains_any(combined_text, ["current-limiting resistor"]):
                        checks["fix_plan_phrase_current_limiting_resistor"] = True
                    # INPUT_PULLUP
                    if contains_any(combined_text, ["input_pullup"]):
                        checks["fix_plan_phrase_input_pullup"] = True
                    # pins 0/1 or RX/TX
                    if contains_any(combined_text, ["pins 0/1", "rx/tx"]):
                        checks["fix_plan_phrase_pins01_or_rx_tx"] = True
                    # millis
                    if contains_any(combined_text, ["millis"]):
                        checks["fix_plan_phrase_millis"] = True
                    # baud rate
                    if contains_any(combined_text, ["baud rate"]):
                        checks["fix_plan_phrase_baud_rate"] = True

            except Exception:
                # JSON parsing failed, leave checks as False
                pass

    # -----------------------------
    # Updated code checks
    # -----------------------------
    checks["has_updated_code"] = os.path.isfile(updated_code_path)
    checks["code_has_millis_call"] = False
    checks["code_has_input_pullup"] = False
    checks["code_has_serial_begin"] = False
    checks["code_has_F_macro"] = False
    checks["code_has_no_delay_call"] = False

    if checks["has_updated_code"]:
        code_text = read_text(updated_code_path)
        if isinstance(code_text, str):
            # Must contain exact substrings
            if "millis(" in code_text:
                checks["code_has_millis_call"] = True
            if "INPUT_PULLUP" in code_text:
                checks["code_has_input_pullup"] = True
            if "Serial.begin" in code_text:
                checks["code_has_serial_begin"] = True
            if 'F("' in code_text:
                checks["code_has_F_macro"] = True
            # Must not contain "delay("
            if "delay(" not in code_text:
                checks["code_has_no_delay_call"] = True

    # -----------------------------
    # Compute reward
    # -----------------------------
    # Count total checks and passed checks
    check_items = [k for k in checks.keys()]
    total = len(check_items)
    passed = sum(1 for k in check_items if checks[k])

    reward = 0.0
    if total > 0:
        reward = passed / total

    # Ensure baseline no-op yields 0.0 when output is empty or missing
    # If none of the three files exist, force reward to 0.0
    if not (checks["has_diagnosis"] or checks["has_fix_plan"] or checks["has_updated_code"]):
        reward = 0.0

    # Compose result
    result = {"reward": round(reward, 6)}
    # Include all checks in the output JSON
    result.update(checks)

    last_non_empty_print(result)

if __name__ == "__main__":
    main()