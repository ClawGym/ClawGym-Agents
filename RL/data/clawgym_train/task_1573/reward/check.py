import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def line_contains_both(line, a, b):
    l = line.lower()
    return (a in l) and (b in l)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # fixed_sketch.txt checks
        "fixed_exists": False,
        "fixed_contains_millis": False,
        "fixed_no_delay_calls": False,
        "fixed_has_INPUT_PULLUP": False,
        "fixed_no_gpio_on_pins_0_1": False,
        "fixed_no_String_class": False,

        # wiring_fix.md checks
        "wiring_exists": False,
        "wiring_external_servo_power": False,
        "wiring_common_ground": False,
        "wiring_decoupling_caps": False,
        "wiring_led_resistor": False,
        "wiring_no_arduino5v_for_servos": False,
        "wiring_pins_0_1_reserved": False,
        "wiring_mentions_brownout": False,

        # troubleshooting_report.md checks
        "troubleshoot_exists": False,
        "troubleshoot_common_ground": False,
        "troubleshoot_pullups": False,
        "troubleshoot_decoupling": False,
        "troubleshoot_avoid_pins_0_1": False,
        "troubleshoot_baud_rate": False,
    }

    # Paths
    fixed_path = os.path.join(output_dir, "fixed_sketch.txt")
    wiring_path = os.path.join(output_dir, "wiring_fix.md")
    troubleshoot_path = os.path.join(output_dir, "troubleshooting_report.md")

    # fixed_sketch.txt validations
    if os.path.isfile(fixed_path):
        checks["fixed_exists"] = True
        content = read_text(fixed_path) or ""
        content_lower = content.lower()

        if "millis(" in content:
            checks["fixed_contains_millis"] = True

        if "delay(" not in content:
            checks["fixed_no_delay_calls"] = True

        if "INPUT_PULLUP" in content:
            checks["fixed_has_INPUT_PULLUP"] = True

        # Disallow GPIO use on pins 0 or 1 via specific API substrings
        forbidden_gpio_substrings = [
            "pinMode(0", "pinMode(1",
            "digitalWrite(0", "digitalWrite(1",
            "digitalRead(0", "digitalRead(1",
            "analogWrite(0", "analogWrite(1",
        ]
        uses_forbidden = any(s in content for s in forbidden_gpio_substrings)
        checks["fixed_no_gpio_on_pins_0_1"] = not uses_forbidden

        # Disallow String class usage
        checks["fixed_no_String_class"] = ("String" not in content)

    # wiring_fix.md validations
    if os.path.isfile(wiring_path):
        checks["wiring_exists"] = True
        content = read_text(wiring_path) or ""
        content_lower = content.lower()
        lines = (content.splitlines() if content else [])

        # External supply mention and servo
        external_phrases = ["external power", "external supply", "separate supply"]
        mentions_external = any(p in content_lower for p in external_phrases)
        mentions_servo = "servo" in content_lower
        if mentions_external and mentions_servo:
            checks["wiring_external_servo_power"] = True

        if "common ground" in content_lower:
            checks["wiring_common_ground"] = True

        if ("0.1uf" in content_lower) or ("decoupling" in content_lower):
            checks["wiring_decoupling_caps"] = True

        if ("led" in content_lower) and ("resistor" in content_lower):
            checks["wiring_led_resistor"] = True

        # Caution against powering motors/servos from Arduino 5V pin
        phrase_direct = "never power motors from arduino 5v" in content_lower
        phrase_line_with_not = any(line_contains_both(line, "arduino 5v", "not") for line in lines)
        checks["wiring_no_arduino5v_for_servos"] = phrase_direct or phrase_line_with_not

        if ("pins 0 and 1" in content_lower) or ("rx/tx" in content_lower) or ("rx" in content_lower and "tx" in content_lower):
            checks["wiring_pins_0_1_reserved"] = True

        if ("brown-out" in content_lower) or ("brownout" in content_lower):
            checks["wiring_mentions_brownout"] = True

    # troubleshooting_report.md validations
    if os.path.isfile(troubleshoot_path):
        checks["troubleshoot_exists"] = True
        content = read_text(troubleshoot_path) or ""
        content_lower = content.lower()

        if "ground" in content_lower:
            checks["troubleshoot_common_ground"] = True

        if ("pullup" in content_lower) or ("input_pullup" in content_lower):
            checks["troubleshoot_pullups"] = True

        if ("0.1uf" in content_lower) or ("decoupling" in content_lower):
            checks["troubleshoot_decoupling"] = True

        if ("pins 0 and 1" in content_lower) or ("rx/tx" in content_lower) or ("rx" in content_lower and "tx" in content_lower):
            checks["troubleshoot_avoid_pins_0_1"] = True

        if ("baud rate" in content_lower) or ("baud" in content_lower):
            checks["troubleshoot_baud_rate"] = True

    # Compute reward
    # No-op baseline: if none of the three required files exist, reward must be 0.0
    required_exist = checks["fixed_exists"] or checks["wiring_exists"] or checks["troubleshoot_exists"]

    total_checks = len(checks)
    true_checks = sum(1 for v in checks.values() if v)

    if not required_exist:
        reward = 0.0
    else:
        reward = true_checks / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)

    # Print exactly one JSON object on last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()