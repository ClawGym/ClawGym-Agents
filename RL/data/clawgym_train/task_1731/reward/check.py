import json
import os
import re
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # Natal
        "natal_exists": False,
        "natal_has_required_keys": False,
        "natal_positions_has_angles": False,
        "natal_ok": False,
        # Daily
        "daily_exists": False,
        "daily_has_headers": False,
        "daily_has_moon_line": False,
        "daily_has_transits_or_no_major": False,
        "daily_ok": False,
        # Weekly
        "weekly_exists": False,
        "weekly_has_header": False,
        "weekly_has_three_items_or_themes": False,
        "weekly_ok": False,
        # VOC
        "voc_exists": False,
        "voc_has_voc_boolean": False,
        "voc_has_end_fields_when_true": False,
        "voc_ok": False,
    }

    # 1) Check natal.json
    natal_path = os.path.join(output_dir, "natal.json")
    natal_data = None
    if os.path.isfile(natal_path):
        checks["natal_exists"] = True
        natal_data = read_json_file(natal_path)
        if isinstance(natal_data, dict):
            # Required top-level keys
            required_keys = {"birth_data", "positions", "house_cusps", "signs"}
            if required_keys.issubset(set(natal_data.keys())):
                checks["natal_has_required_keys"] = True
                # positions have Ascendant and Midheaven numeric
                positions = natal_data.get("positions", {})
                asc = positions.get("Ascendant", None)
                mc = positions.get("Midheaven", None)
                if is_number(asc) and is_number(mc):
                    checks["natal_positions_has_angles"] = True
    checks["natal_ok"] = checks["natal_exists"] and checks["natal_has_required_keys"] and checks["natal_positions_has_angles"]

    # 2) Check daily_2026-03-15.txt
    daily_path = os.path.join(output_dir, "daily_2026-03-15.txt")
    daily_content = None
    if os.path.isfile(daily_path):
        checks["daily_exists"] = True
        daily_content = read_text_file(daily_path) or ""
        # Headers/markers
        has_transit_context = "TRANSIT CONTEXT" in daily_content
        has_transits_active = "Transits active today" in daily_content
        has_notable = "Notable:" in daily_content
        checks["daily_has_headers"] = has_transit_context and has_transits_active and has_notable

        # Moon line starts with "Moon:"
        lines = daily_content.splitlines()
        moon_line_found = any(l.strip().startswith("Moon:") for l in lines)
        checks["daily_has_moon_line"] = moon_line_found

        # Either contains " natal " or "No major transits active today."
        has_natal_substring = " natal " in daily_content
        has_no_major = "No major transits active today." in daily_content
        checks["daily_has_transits_or_no_major"] = has_natal_substring or has_no_major

    checks["daily_ok"] = checks["daily_exists"] and checks["daily_has_headers"] and checks["daily_has_moon_line"] and checks["daily_has_transits_or_no_major"]

    # 3) Check weekly_2026-03-15.txt
    weekly_path = os.path.join(output_dir, "weekly_2026-03-15.txt")
    weekly_content = None
    if os.path.isfile(weekly_path):
        checks["weekly_exists"] = True
        weekly_content = read_text_file(weekly_path) or ""
        checks["weekly_has_header"] = "WEEK AHEAD" in weekly_content

        # Count numbered entries (lines starting with number and a dot) or occurrences of "theme:"
        lines = weekly_content.splitlines()
        numbered_count = 0
        num_re = re.compile(r"^\s*\d+\.")
        for l in lines:
            if num_re.match(l):
                numbered_count += 1
        theme_count = weekly_content.count("theme:")
        checks["weekly_has_three_items_or_themes"] = (numbered_count >= 3) or (theme_count >= 3)

    checks["weekly_ok"] = checks["weekly_exists"] and checks["weekly_has_header"] and checks["weekly_has_three_items_or_themes"]

    # 4) Check voc.json
    voc_path = os.path.join(output_dir, "voc.json")
    voc_data = None
    if os.path.isfile(voc_path):
        checks["voc_exists"] = True
        voc_data = read_json_file(voc_path)
        if isinstance(voc_data, dict) and "voc" in voc_data and isinstance(voc_data["voc"], bool):
            checks["voc_has_voc_boolean"] = True
            voc_val = voc_data["voc"]
            if voc_val is True:
                end_sign_ok = "end_sign" in voc_data and isinstance(voc_data["end_sign"], str)
                duration_ok = "duration_hours" in voc_data and is_number(voc_data["duration_hours"])
                if end_sign_ok and duration_ok:
                    checks["voc_has_end_fields_when_true"] = True
            else:
                # If voc is False, end fields are not required for pass
                checks["voc_has_end_fields_when_true"] = True

    checks["voc_ok"] = checks["voc_exists"] and checks["voc_has_voc_boolean"] and checks["voc_has_end_fields_when_true"]

    # Compute reward: equal weight for four artifacts
    artifact_bools = [checks["natal_ok"], checks["daily_ok"], checks["weekly_ok"], checks["voc_ok"]]
    reward = sum(1.0 for b in artifact_bools if b) / 4.0

    # Ensure 0.0 for no-op baseline if nothing in output or no files present
    # (This is already handled by the calculation, but keep explicit behavior)
    if not any([checks["natal_exists"], checks["daily_exists"], checks["weekly_exists"], checks["voc_exists"]]):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()