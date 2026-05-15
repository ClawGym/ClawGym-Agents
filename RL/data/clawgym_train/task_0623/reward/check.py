import json
import os
import sys
import re

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Natal chart
        "natal_exists": False,
        "natal_is_json": False,
        "natal_has_required_keys": False,
        # Daily report
        "daily_exists": False,
        "daily_prefix_ok": False,
        "daily_has_moon_line": False,
        "daily_has_section_header": False,
        "daily_has_notable_line": False,
        # Weekly report
        "weekly_exists": False,
        "weekly_prefix_ok": False,
        "weekly_has_numbered_item": False,
        # VoC
        "voc_exists": False,
        "voc_is_json": False,
        "voc_has_voc_boolean": False,
        "voc_conditional_fields_ok": False,
        # Summary
        "summary_exists": False,
        "summary_word_count_ok": False,
        "summary_headers_order_ok": False,
    }

    # 1) natal.json checks
    natal_path = os.path.join(output_dir, "natal.json")
    if os.path.isfile(natal_path):
        checks["natal_exists"] = True
        natal_obj = load_json(natal_path)
        if isinstance(natal_obj, dict):
            checks["natal_is_json"] = True
            required_keys = {"birth_data", "positions", "house_cusps", "signs"}
            if required_keys.issubset(natal_obj.keys()):
                checks["natal_has_required_keys"] = True

    # 2) daily.txt checks
    daily_path = os.path.join(output_dir, "daily.txt")
    if os.path.isfile(daily_path):
        checks["daily_exists"] = True
        txt = load_text(daily_path) or ""
        lines = txt.splitlines()
        if lines:
            first = lines[0]
            if first.startswith("TRANSIT CONTEXT —"):
                checks["daily_prefix_ok"] = True
        # Moon line
        for ln in lines:
            if ln.startswith("Moon:"):
                checks["daily_has_moon_line"] = True
                break
        # Section header
        if "Transits active today" in txt:
            checks["daily_has_section_header"] = True
        # Notable line
        for ln in lines:
            if ln.startswith("Notable:"):
                checks["daily_has_notable_line"] = True
                break

    # 3) weekly.txt checks
    weekly_path = os.path.join(output_dir, "weekly.txt")
    if os.path.isfile(weekly_path):
        checks["weekly_exists"] = True
        wtxt = load_text(weekly_path) or ""
        wlines = wtxt.splitlines()
        if wlines:
            if wlines[0].startswith("WEEK AHEAD —"):
                checks["weekly_prefix_ok"] = True
        # At least one numbered item line starting with "1."
        for ln in wlines:
            if ln.startswith("1."):
                checks["weekly_has_numbered_item"] = True
                break

    # 4) voc.json checks
    voc_path = os.path.join(output_dir, "voc.json")
    if os.path.isfile(voc_path):
        checks["voc_exists"] = True
        voc_obj = load_json(voc_path)
        if isinstance(voc_obj, dict):
            checks["voc_is_json"] = True
            if "voc" in voc_obj and isinstance(voc_obj["voc"], bool):
                checks["voc_has_voc_boolean"] = True
                if voc_obj["voc"] is True:
                    # Must include end_time_utc and end_sign
                    if "end_time_utc" in voc_obj and "end_sign" in voc_obj:
                        checks["voc_conditional_fields_ok"] = True
                else:
                    # If false, extra fields are optional; condition passes
                    checks["voc_conditional_fields_ok"] = True

    # 5) summary.md checks
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        stext = load_text(summary_path) or ""
        # Word count 300–500 inclusive
        words = re.findall(r"\b\w+\b", stext)
        wc = len(words)
        if 300 <= wc <= 500:
            checks["summary_word_count_ok"] = True
        # Headers in exact order on their own lines
        required_headers = ["Top Transit", "Week Theme", "VoC Advisory", "Planning Tips"]
        slines = [ln.strip() for ln in stext.splitlines()]
        header_positions = []
        for hdr in required_headers:
            try:
                if not header_positions:
                    idx = slines.index(hdr)
                else:
                    # find after last index
                    start = header_positions[-1] + 1
                    idx = slines.index(hdr, start)
                header_positions.append(idx)
            except ValueError:
                header_positions = []
                break
        if header_positions and len(header_positions) == 4 and header_positions == sorted(header_positions):
            checks["summary_headers_order_ok"] = True

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()