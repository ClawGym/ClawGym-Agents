import json
import os
import sys

def word_count(s: str) -> int:
    if not isinstance(s, str):
        return 0
    return len([w for w in s.strip().split() if w])

def substrings_in_order(text: str, substrings) -> bool:
    if not isinstance(text, str):
        return False
    idx = 0
    # Must start with "For "
    if not text.startswith("For "):
        return False
    for sub in substrings:
        pos = text.find(sub, idx)
        if pos == -1:
            return False
        idx = pos + len(sub)
    return True

def parse_txt_sections(lines, expected_headings):
    # Find indices of headings in order; headings must appear as exact lines (ignoring surrounding spaces)
    indices = []
    start = 0
    for heading in expected_headings:
        found = -1
        for i in range(start, len(lines)):
            if lines[i].strip() == heading:
                found = i
                break
        if found == -1:
            return False, []
        indices.append(found)
        start = found + 1
    return True, indices

def count_bullet_lines(lines):
    count = 0
    for ln in lines:
        s = ln.lstrip()
        if s.startswith("- "):
            count += 1
    return count

def competitive_vs_in_lines(lines):
    for ln in lines:
        s = ln.strip().lower()
        if s.startswith("versus") or ("vs" in s):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "json_exists": False,
        "txt_exists": False,
        "both_outputs_exist": False,
        "json_parsed": False,
        "json_keys_present": False,
        "one_liner_len_ok": False,
        "elevator_pitch_len_ok": False,
        "key_differentiators_count_three": False,
        "key_differentiators_nonempty": False,
        "positioning_statement_template_ok": False,
        "competitive_position_format_ok": False,
        "txt_headings_order_ok": False,
        "txt_key_differentiators_three_lines": False,
        "txt_competitive_position_contains_vs": False,
    }

    json_path = os.path.join(output_dir, "positioning.json")
    txt_path = os.path.join(output_dir, "positioning.txt")

    # Existence checks
    checks["json_exists"] = os.path.isfile(json_path)
    checks["txt_exists"] = os.path.isfile(txt_path)
    checks["both_outputs_exist"] = checks["json_exists"] and checks["txt_exists"]

    # JSON validations
    data = None
    if checks["json_exists"]:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                checks["json_parsed"] = True
        except Exception:
            checks["json_parsed"] = False

    if checks["json_parsed"]:
        required_keys = [
            "positioning_statement",
            "one_liner",
            "elevator_pitch",
            "key_differentiators",
            "target_customer_profile",
            "competitive_position",
        ]
        if all(k in data for k in required_keys):
            checks["json_keys_present"] = True

        # One-liner length <= 10 words
        one_liner = data.get("one_liner")
        if isinstance(one_liner, str) and word_count(one_liner) <= 10 and word_count(one_liner) > 0:
            checks["one_liner_len_ok"] = True

        # Elevator pitch 60–100 words inclusive
        elevator_pitch = data.get("elevator_pitch")
        wc = word_count(elevator_pitch) if isinstance(elevator_pitch, str) else 0
        if isinstance(elevator_pitch, str) and 60 <= wc <= 100:
            checks["elevator_pitch_len_ok"] = True

        # Key differentiators array exactly 3 non-empty strings
        kdiff = data.get("key_differentiators")
        if isinstance(kdiff, list) and len(kdiff) == 3:
            checks["key_differentiators_count_three"] = True
            if all(isinstance(x, str) and len(x.strip()) > 0 for x in kdiff):
                checks["key_differentiators_nonempty"] = True

        # Positioning statement template structure and order
        p_stmt = data.get("positioning_statement")
        # Enforce exact substrings in order and startswith "For "
        substrings = [" who ", " is a ", " that ", "Unlike ", " we "]
        if isinstance(p_stmt, str) and substrings_in_order(p_stmt, substrings):
            checks["positioning_statement_template_ok"] = True

        # Competitive position includes 'vs' or starts with 'Versus'
        comp = data.get("competitive_position")
        if isinstance(comp, str):
            comp_s = comp.strip()
            comp_lower = comp_s.lower()
            if comp_lower.startswith("versus") or ("vs" in comp_lower):
                checks["competitive_position_format_ok"] = True

    # TXT validations
    lines = []
    if checks["txt_exists"]:
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                # Ensure we treat it as plain text
                content = f.read()
                lines = content.splitlines()
        except Exception:
            lines = []

    if lines:
        expected_headings = [
            "1. Positioning Statement",
            "2. One-Liner",
            "3. Elevator Pitch",
            "4. Key Differentiators",
            "5. Target Customer Profile",
            "6. Competitive Position",
        ]
        ok_order, idxs = parse_txt_sections(lines, expected_headings)
        if ok_order:
            checks["txt_headings_order_ok"] = True
            # Key Differentiators section content is between heading 4 and heading 5
            start_kd = idxs[3] + 1
            end_kd = idxs[4]
            kd_section_lines = lines[start_kd:end_kd]
            if count_bullet_lines(kd_section_lines) == 3:
                checks["txt_key_differentiators_three_lines"] = True
            # Competitive section content is from heading 6 to end
            start_comp = idxs[5] + 1
            comp_lines = lines[start_comp:]
            if competitive_vs_in_lines(comp_lines):
                checks["txt_competitive_position_contains_vs"] = True

    # Compute reward
    # Gate: if both required files do not exist, reward must be 0.0
    if not checks["both_outputs_exist"]:
        reward = 0.0
    else:
        scored_keys = [
            "json_parsed",
            "json_keys_present",
            "one_liner_len_ok",
            "elevator_pitch_len_ok",
            "key_differentiators_count_three",
            "key_differentiators_nonempty",
            "positioning_statement_template_ok",
            "competitive_position_format_ok",
            "txt_headings_order_ok",
            "txt_key_differentiators_three_lines",
            "txt_competitive_position_contains_vs",
        ]
        total = len(scored_keys)
        passed = sum(1 for k in scored_keys if checks.get(k, False))
        reward = passed / total if total > 0 else 0.0

    result = {"reward": float(max(0.0, min(1.0, reward)))}
    result.update(checks)
    # Print exactly one JSON object on the last non-empty stdout line
    print(json.dumps(result))

if __name__ == "__main__":
    main()