import json
import os
import sys

# Workspace root handling
workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Helper: read text file safely
def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

# Minimal YAML section parser tailored to expected structure:
# Expects a top-level "yesno:" and "menu:".
# Under each, either:
# - "options:" followed by a list of items:
#     - key-value pairs per item (indented)
# Keys we care about: desc/description, a, id.
# For yesno, alternative form with "yes:" and "no:" subsections is supported.
def parse_menu_requirements(yaml_text):
    if yaml_text is None:
        return None
    lines_all = []
    for raw in yaml_text.splitlines():
        # Keep indentation; strip trailing spaces; ignore pure comment lines
        if raw.strip().startswith("#") or raw.strip() == "":
            continue
        # Normalize tabs to spaces (YAML should be spaces, but be lenient)
        raw = raw.rstrip("\n").rstrip("\r").replace("\t", "    ")
        lines_all.append(raw)
    # Utility: compute indent
    def indent_of(s):
        return len(s) - len(s.lstrip(" "))
    # Find section blocks by top-level keys
    def extract_section(name):
        start_idx = None
        for i, ln in enumerate(lines_all):
            if ln.lstrip().startswith(name + ":") and indent_of(ln) == 0:
                start_idx = i
                break
        if start_idx is None:
            return []
        base_indent = indent_of(lines_all[start_idx])
        block = []
        for j in range(start_idx + 1, len(lines_all)):
            ln = lines_all[j]
            if indent_of(ln) <= base_indent and ln.lstrip().endswith(":"):
                # Next top-level or equal-level section starts
                break
            block.append(ln)
        return block

    def parse_kv_value(val):
        v = val.strip()
        if v.startswith('"') and v.endswith('"') and len(v) >= 2:
            return v[1:-1]
        if v.startswith("'") and v.endswith("'") and len(v) >= 2:
            return v[1:-1]
        return v

    def parse_kv_line(ln):
        # Expects "key: value" form
        if ":" not in ln:
            return None, None
        key, rest = ln.split(":", 1)
        key = key.strip()
        val = rest.strip()
        if val == "":
            return key, None
        return key, parse_kv_value(val)

    def parse_options_from_block(block_lines):
        items = []
        i = 0
        # Locate 'options:' line (may already be inside options context if caller wants)
        # Here, assume block_lines start after 'options:' or include it; we will scan accordingly.
        # Strategy: If we find 'options:' treat subsequent list items; else parse list items at current level.
        # First, find the options indent if present.
        opt_idx = None
        opt_indent = None
        for k, ln in enumerate(block_lines):
            s = ln.lstrip()
            if s.startswith("options:"):
                opt_idx = k
                opt_indent = indent_of(ln)
                break
        start_i = opt_idx + 1 if opt_idx is not None else 0
        list_indent = None
        # Determine indent level where "- " items appear
        # Scan from start_i to find first "- "
        for k in range(start_i, len(block_lines)):
            ln = block_lines[k]
            s = ln.lstrip()
            if s.startswith("- "):
                list_indent = indent_of(ln)
                start_i = k
                break
        if list_indent is None:
            # No list found
            return items
        i = start_i
        current_item = None
        current_item_indent = None
        while i < len(block_lines):
            ln = block_lines[i]
            s = ln.lstrip()
            ind = indent_of(ln)
            if ind < list_indent:
                # End of list
                break
            if s.startswith("- ") and ind == list_indent:
                # Start a new item
                if current_item is not None:
                    items.append(current_item)
                current_item = {}
                current_item_indent = ind
                after = s[2:].strip()
                if after:
                    # Could be inline "key: value"
                    if ":" in after:
                        k, v = parse_kv_line(after)
                        if k is not None:
                            current_item[k] = v
                    else:
                        # Treat as description if provided as scalar
                        current_item["desc"] = after
                i += 1
                continue
            # Within current item: parse key: value under deeper indent
            if current_item is not None and ind > current_item_indent:
                if ":" in s:
                    k, v = parse_kv_line(s)
                    if k is not None:
                        current_item[k] = v
                i += 1
                continue
            # Other cases: move forward
            i += 1
        if current_item is not None:
            items.append(current_item)
        return items

    def parse_yesno_from_block(block_lines):
        # Two possible forms: options list, or 'yes:' and 'no:' subsections
        # Try options list first
        items = parse_options_from_block(block_lines)
        items_clean = []
        if items:
            for it in items:
                desc = it.get("desc") or it.get("description") or ""
                a = it.get("a")
                idv = it.get("id")
                entry = {}
                if a is not None:
                    entry["a"] = str(a)
                if idv is not None:
                    entry["id"] = str(idv)
                entry["desc"] = str(desc)
                items_clean.append(entry)
            return items_clean
        # Fallback: parse 'yes:' and 'no:' subsections
        # We'll iterate lines, detect keys ending with ':' at some indent > 0
        subsections = []
        i = 0
        while i < len(block_lines):
            ln = block_lines[i]
            s = ln.lstrip()
            ind = indent_of(ln)
            if s.endswith(":") and not s.startswith("- "):
                key = s[:-1].strip()
                # Collect its inner kv pairs
                kv = {}
                i += 1
                while i < len(block_lines):
                    ln2 = block_lines[i]
                    s2 = ln2.lstrip()
                    ind2 = indent_of(ln2)
                    if ind2 <= ind:
                        break
                    if ":" in s2:
                        k, v = parse_kv_line(s2)
                        if k is not None:
                            kv[k] = v
                    i += 1
                subsections.append((key, kv))
            else:
                i += 1
        # Preserve order of appearance
        items_clean = []
        for name, kv in subsections:
            desc = kv.get("desc") or kv.get("description") or ""
            a = kv.get("a")
            idv = kv.get("id")
            entry = {}
            if a is not None:
                entry["a"] = str(a)
            if idv is not None:
                entry["id"] = str(idv)
            entry["desc"] = str(desc)
            items_clean.append(entry)
        return items_clean

    # Parse sections
    yesno_block = extract_section("yesno")
    menu_block = extract_section("menu")

    yesno_items = parse_yesno_from_block(yesno_block)
    # For menu, expect options list
    menu_items = parse_options_from_block(menu_block)
    menu_items_clean = []
    for it in menu_items:
        desc = it.get("desc") or it.get("description") or ""
        a = it.get("a")
        idv = it.get("id")
        entry = {}
        if a is not None:
            entry["a"] = str(a)
        if idv is not None:
            entry["id"] = str(idv)
        entry["desc"] = str(desc)
        menu_items_clean.append(entry)

    result = {"yesno": yesno_items, "menu": menu_items_clean}
    return result

# Helpers for validation
def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_single_row_buttons(obj):
    # buttons must be an array with exactly one inner array
    if not isinstance(obj, list):
        return False
    if len(obj) != 1:
        return False
    if not isinstance(obj[0], list):
        return False
    return True

def all_button_label_lengths_ok(buttons_row, max_len=3):
    for b in buttons_row:
        if not isinstance(b, dict):
            return False
        t = b.get("text")
        if not isinstance(t, str):
            return False
        if len(t) < 1 or len(t) > max_len:
            return False
    return True

def parse_callback_json(cb_str):
    try:
        obj = json.loads(cb_str)
        if not isinstance(obj, dict):
            return None
        # Only 'a' and optional 'id' allowed
        for k in obj.keys():
            if k not in ("a", "id"):
                return None
        if "a" not in obj:
            return None
        if not isinstance(obj["a"], str):
            return None
        if len(obj["a"]) < 1 or len(obj["a"]) > 20:
            return None
        if "id" in obj:
            if not isinstance(obj["id"], str):
                return None
            if len(obj["id"]) < 1 or len(obj["id"]) > 16:
                return None
        return obj
    except Exception:
        return None

def check_callback_data_compact_and_valid(buttons_row):
    # Return tuple: (all_valid, actions_list, ids_list, all_len_ok)
    actions = []
    ids = []
    all_valid = True
    all_len_ok = True
    for b in buttons_row:
        if not isinstance(b, dict):
            all_valid = False
            continue
        cbs = b.get("callback_data")
        if not isinstance(cbs, str):
            all_valid = False
            continue
        # Length <= 64 bytes utf-8
        if len(cbs.encode("utf-8")) > 64:
            all_len_ok = False
        parsed = parse_callback_json(cbs)
        if parsed is None:
            all_valid = False
        else:
            actions.append(parsed.get("a"))
            ids.append(parsed.get("id"))
    return all_valid, actions, ids, all_len_ok

def extract_desc_from_line(line):
    # Extract description after first em dash or hyphen surrounded by spaces
    # Accept patterns like "1 — Desc", "1 - Desc", "Yes — Desc", "No - Desc"
    # Find the delimiter '—' or '-' with spaces around
    idx = None
    for delim in [" — ", " - "]:
        if delim in line:
            idx = line.find(delim)
            if idx != -1:
                return line[idx + len(delim):].strip()
    # Fallback: if there is any '-' or '—' use first occurrence
    for ch in ["—", "-"]:
        p = line.find(ch)
        if p != -1:
            return line[p+1:].strip()
    return None

def line_starts_with_numbered(i, line):
    # Check if line starts with digit i followed by dash/em dash and space
    prefix1 = f"{i} — "
    prefix2 = f"{i} - "
    return line.startswith(prefix1) or line.startswith(prefix2)

def format_checks_summary(checks):
    # Build result JSON: reward numeric [0,1], plus boolean checks
    # Only count artifact-dependent checks for reward.
    artifact_checks = [k for k in checks.keys() if k not in ("yaml_parsed",)]
    passed = sum(1 for k in artifact_checks if checks.get(k) is True)
    total = len(artifact_checks)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Enforce no-op baseline: if no outputs exist, reward must be 0.0
    any_outputs = False
    for p in ["prompt_yesno.json", "prompt_yesno_fallback.txt", "prompt_menu.json", "prompt_menu_fallback.txt"]:
        if os.path.isfile(os.path.join(output_dir, p)):
            any_outputs = True
            break
    if not any_outputs:
        reward = 0.0
    # Compose final dict
    out = {"reward": round(reward, 6)}
    out.update(checks)
    return out

# Initialize checks dict with all False
checks = {
    # YAML input dependency
    "yaml_parsed": False,
    # Yes/No JSON checks
    "yesno_json_present": False,
    "yesno_buttons_single_row": False,
    "yesno_buttons_count_2": False,
    "yesno_button_labels_len_ok": False,
    "yesno_callback_json_valid": False,
    "yesno_callback_len_ok": False,
    "yesno_callback_actions_distinct": False,
    "yesno_message_two_lines_format": False,
    "yesno_message_yesno_keywords": False,
    "yesno_message_descs_match_yaml_order": False,
    "yesno_buttons_actions_match_yaml_order": False,
    # Yes/No fallback checks
    "yesno_fallback_present": False,
    "yesno_fallback_three_lines_format": False,
    "yesno_fallback_descs_match_yaml_order": False,
    "yesno_cross_button_fallback_count_match": False,
    # Menu JSON checks
    "menu_json_present": False,
    "menu_buttons_single_row": False,
    "menu_buttons_count_6": False,
    "menu_button_labels_1_to_6": False,
    "menu_button_labels_len_ok": False,
    "menu_callback_json_valid": False,
    "menu_callback_len_ok": False,
    "menu_callback_actions_distinct": False,
    "menu_message_six_lines_format": False,
    "menu_message_descs_match_yaml_order": False,
    "menu_buttons_actions_match_yaml_order": False,
    # Menu fallback checks
    "menu_fallback_present": False,
    "menu_fallback_seven_lines_format": False,
    "menu_fallback_descs_match_yaml_order": False,
    "menu_cross_button_fallback_count_match": False,
}

# Load YAML input
yaml_path = os.path.join(input_dir, "menu_requirements.yaml")
yaml_text = read_text(yaml_path)
parsed_yaml = parse_menu_requirements(yaml_text) if yaml_text is not None else None
if parsed_yaml and isinstance(parsed_yaml, dict):
    checks["yaml_parsed"] = True

# Expected order and descriptions from YAML
expected_yesno_descs = []
expected_yesno_actions = []
if parsed_yaml and isinstance(parsed_yaml.get("yesno"), list):
    for item in parsed_yaml["yesno"]:
        expected_yesno_descs.append(item.get("desc", ""))
        if "a" in item:
            expected_yesno_actions.append(item["a"])

expected_menu_descs = []
expected_menu_actions = []
if parsed_yaml and isinstance(parsed_yaml.get("menu"), list):
    for item in parsed_yaml["menu"]:
        expected_menu_descs.append(item.get("desc", ""))
        if "a" in item:
            expected_menu_actions.append(item["a"])

# YES/NO JSON
yesno_json_path = os.path.join(output_dir, "prompt_yesno.json")
yesno_obj = load_json_file(yesno_json_path)
if isinstance(yesno_obj, dict):
    checks["yesno_json_present"] = True
    # Validate keys
    msg = yesno_obj.get("message")
    btns = yesno_obj.get("buttons")
    # buttons structure
    if is_single_row_buttons(btns):
        checks["yesno_buttons_single_row"] = True
        row = btns[0]
        if isinstance(row, list) and len(row) == 2:
            checks["yesno_buttons_count_2"] = True
        # label length
        if isinstance(row, list) and len(row) >= 1:
            if all_button_label_lengths_ok(row):
                checks["yesno_button_labels_len_ok"] = True
            # callback data valid and compact
            valid_cb, actions_list, ids_list, len_ok = check_callback_data_compact_and_valid(row)
            if valid_cb:
                checks["yesno_callback_json_valid"] = True
            if len_ok:
                checks["yesno_callback_len_ok"] = True
            # distinct actions
            if len(actions_list) == len(set(actions_list)) and len(actions_list) == 2:
                checks["yesno_callback_actions_distinct"] = True
            # Compare actions order with YAML if available
            if checks["yaml_parsed"] and expected_yesno_actions and len(expected_yesno_actions) == len(actions_list):
                if actions_list == expected_yesno_actions:
                    checks["yesno_buttons_actions_match_yaml_order"] = True
    # message format
    if isinstance(msg, str):
        lines = [ln for ln in msg.split("\n") if ln.strip() != ""]
        if len(lines) == 2:
            # first line must contain Yes or Y; second line must contain No or N (case-insensitive)
            ok_keywords = (("yes" in lines[0].lower() or lines[0].strip().lower().startswith("y")),
                           ("no" in lines[1].lower() or lines[1].strip().lower().startswith("n")))
            if all(ok_keywords):
                checks["yesno_message_yesno_keywords"] = True
            checks["yesno_message_two_lines_format"] = True
            # Compare descriptions in order with YAML
            if checks["yaml_parsed"] and expected_yesno_descs and len(expected_yesno_descs) == 2:
                descs_from_msg = []
                for ln in lines:
                    d = extract_desc_from_line(ln)
                    descs_from_msg.append("" if d is None else d)
                if descs_from_msg == expected_yesno_descs:
                    checks["yesno_message_descs_match_yaml_order"] = True

# YES/NO fallback
yesno_fb_path = os.path.join(output_dir, "prompt_yesno_fallback.txt")
yesno_fb_text = read_text(yesno_fb_path)
if isinstance(yesno_fb_text, str):
    checks["yesno_fallback_present"] = True
    fb_lines = [ln for ln in yesno_fb_text.split("\n") if ln.strip() != ""]
    if len(fb_lines) == 3:
        # first two numbered lines then exact instruction
        numbered_ok = line_starts_with_numbered(1, fb_lines[0]) and line_starts_with_numbered(2, fb_lines[1])
        instruction_ok = fb_lines[2].strip() == "Reply with the number to choose."
        if numbered_ok and instruction_ok:
            checks["yesno_fallback_three_lines_format"] = True
        # compare descriptions with YAML
        if checks["yaml_parsed"] and expected_yesno_descs and len(expected_yesno_descs) == 2:
            descs_from_fb = []
            for ln in fb_lines[:2]:
                d = extract_desc_from_line(ln)
                descs_from_fb.append("" if d is None else d)
            if descs_from_fb == expected_yesno_descs:
                checks["yesno_fallback_descs_match_yaml_order"] = True

# Cross yesno: button count vs fallback count
if checks["yesno_json_present"] and checks["yesno_fallback_present"]:
    try:
        row_len = len(yesno_obj.get("buttons", [])[0])
    except Exception:
        row_len = None
    fb_count = None
    try:
        fb_lines = [ln for ln in yesno_fb_text.split("\n") if ln.strip() != ""]
        fb_count = 2  # first two are options
    except Exception:
        fb_count = None
    if isinstance(row_len, int) and isinstance(fb_count, int) and row_len == fb_count:
        checks["yesno_cross_button_fallback_count_match"] = True

# MENU JSON
menu_json_path = os.path.join(output_dir, "prompt_menu.json")
menu_obj = load_json_file(menu_json_path)
if isinstance(menu_obj, dict):
    checks["menu_json_present"] = True
    msg = menu_obj.get("message")
    btns = menu_obj.get("buttons")
    if is_single_row_buttons(btns):
        checks["menu_buttons_single_row"] = True
        row = btns[0]
        if isinstance(row, list) and len(row) == 6:
            checks["menu_buttons_count_6"] = True
        # labels must be "1".."6" in order
        labels_ok = False
        if isinstance(row, list) and len(row) >= 6:
            labels = [b.get("text") if isinstance(b, dict) else None for b in row[:6]]
            labels_ok = labels == ["1", "2", "3", "4", "5", "6"]
            if labels_ok:
                checks["menu_button_labels_1_to_6"] = True
            if all_button_label_lengths_ok(row[:6]):
                checks["menu_button_labels_len_ok"] = True
            # callback data checks
            valid_cb, actions_list, ids_list, len_ok = check_callback_data_compact_and_valid(row[:6])
            if valid_cb:
                checks["menu_callback_json_valid"] = True
            if len_ok:
                checks["menu_callback_len_ok"] = True
            if len(actions_list) == len(set(actions_list)) and len(actions_list) == 6:
                checks["menu_callback_actions_distinct"] = True
            # Compare actions order with YAML if available
            if checks["yaml_parsed"] and expected_menu_actions and len(expected_menu_actions) == len(actions_list):
                if actions_list == expected_menu_actions:
                    checks["menu_buttons_actions_match_yaml_order"] = True
    # message format: exactly 6 non-empty lines each starting with i dash/em dash
    if isinstance(msg, str):
        lines = [ln for ln in msg.split("\n") if ln.strip() != ""]
        if len(lines) == 6:
            format_ok = True
            for i, ln in enumerate(lines, start=1):
                if not line_starts_with_numbered(i, ln):
                    format_ok = False
                    break
            if format_ok:
                checks["menu_message_six_lines_format"] = True
            # Compare descriptions with YAML
            if checks["yaml_parsed"] and expected_menu_descs and len(expected_menu_descs) == 6:
                descs_from_msg = [extract_desc_from_line(ln) or "" for ln in lines]
                if descs_from_msg == expected_menu_descs:
                    checks["menu_message_descs_match_yaml_order"] = True

# MENU fallback
menu_fb_path = os.path.join(output_dir, "prompt_menu_fallback.txt")
menu_fb_text = read_text(menu_fb_path)
if isinstance(menu_fb_text, str):
    checks["menu_fallback_present"] = True
    fb_lines = [ln for ln in menu_fb_text.split("\n") if ln.strip() != ""]
    if len(fb_lines) == 7:
        numbered_ok = True
        for i in range(1, 7):
            if not line_starts_with_numbered(i, fb_lines[i-1]):
                numbered_ok = False
                break
        instruction_ok = fb_lines[6].strip() == "Reply with the number to choose."
        if numbered_ok and instruction_ok:
            checks["menu_fallback_seven_lines_format"] = True
        # Compare descriptions with YAML
        if checks["yaml_parsed"] and expected_menu_descs and len(expected_menu_descs) == 6:
            descs_from_fb = [extract_desc_from_line(ln) or "" for ln in fb_lines[:6]]
            if descs_from_fb == expected_menu_descs:
                checks["menu_fallback_descs_match_yaml_order"] = True

# Cross menu: button count vs fallback count
if checks["menu_json_present"] and checks["menu_fallback_present"]:
    try:
        row_len = len(menu_obj.get("buttons", [])[0])
    except Exception:
        row_len = None
    fb_count = None
    try:
        fb_lines = [ln for ln in menu_fb_text.split("\n") if ln.strip() != ""]
        fb_count = 6  # first six are options
    except Exception:
        fb_count = None
    if isinstance(row_len, int) and isinstance(fb_count, int) and row_len == fb_count:
        checks["menu_cross_button_fallback_count_match"] = True

# Emit result JSON (one line)
result = format_checks_summary(checks)
print(json.dumps(result))