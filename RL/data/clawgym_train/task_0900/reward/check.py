#!/usr/bin/env python3
import json
import os
import re
import sys

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def parse_jsonl_lines(path):
    res = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    res.append(obj)
                except Exception:
                    return None, "invalid_json_line"
        return res, None
    except Exception as e:
        return None, str(e)

def is_int(n):
    return isinstance(n, int) and not isinstance(n, bool)

def simple_yaml_parse(text):
    # Minimal YAML mapping parser:
    # - Supports top-level keys: key: value
    # - Supports nested mapping under a key via indented lines "  subkey: value"
    # - Treats everything as strings or dicts
    data = {}
    current_key = None
    lines = text.splitlines()
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        # Top-level key
        if not line.startswith(" "):
            m = re.match(r'^([A-Za-z0-9_\-]+)\s*:\s*(.*)$', line)
            if m:
                key = m.group(1)
                val = m.group(2)
                if val == "" or val is None:
                    data[key] = {}
                    current_key = key
                else:
                    data[key] = val
                    current_key = key if isinstance(val, dict) else None
            else:
                # Not a key-value; skip
                current_key = None
        else:
            # Indented - nested key under current_key
            if current_key is None:
                continue
            if not isinstance(data.get(current_key), dict):
                # If previously scalar, convert to dict
                data[current_key] = {}
            m2 = re.match(r'^\s{2,}([A-Za-z0-9_\-]+)\s*:\s*(.*)$', line)
            if m2:
                subk = m2.group(1)
                subv = m2.group(2)
                data[current_key][subk] = subv if subv is not None else ""
            # ignore list items and other constructs
    return data

def extract_moltcaptcha_requirements(challenge_text):
    text = challenge_text.lower()
    # confirm haiku and 3 lines mention
    mentions_haiku = "haiku" in text
    mentions_three = ("3-line" in text) or ("3 line" in text) or ("three lines" in text) or ("three-line" in text) or ("3 sentences" in text)  # tolerant

    # find ASCII target between 280 and 320; ensure it's tied to ASCII mention
    ascii_target = None
    # Look for "ascii" within up to 100 chars of a 3-digit number
    for m in re.finditer(r'ascii[^0-9]{0,100}?(\d{3})', challenge_text, flags=re.IGNORECASE | re.DOTALL):
        num = int(m.group(1))
        if 280 <= num <= 320:
            ascii_target = num
            break
    if ascii_target is None:
        # Fallback: any 3-digit number in range if ASCII mentioned anywhere
        if "ascii" in text:
            for m in re.finditer(r'(\d{3})', challenge_text):
                num = int(m.group(1))
                if 280 <= num <= 320:
                    ascii_target = num
                    break

    # find total word count N
    N = None
    # Prefer phrases containing "word"
    m = re.search(r'(?:word count|total words|total word count|words)\D+?(\d+)', challenge_text, flags=re.IGNORECASE)
    if m:
        N = int(m.group(1))
    else:
        # fallback: look for "exactly N words"
        m2 = re.search(r'exactly\s+(\d+)\s+words', challenge_text, flags=re.IGNORECASE)
        if m2:
            N = int(m2.group(1))

    return mentions_haiku, mentions_three, ascii_target, N

def count_words(text):
    # Count words as sequences of alphanumerics/underscore bounded by word boundaries
    return len(re.findall(r'\b\w+\b', text))

def first_char_ascii_sum(lines):
    total = 0
    for line in lines:
        s = line.lstrip("\r\n")
        if not s:
            return None
        total += ord(s[0])
    return total

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "assessments_exists": False,
        "assessments_parse_and_len_ge4": False,
        "assessments_items_valid": False,
        "followups_exists": False,
        "followups_valid_for_required": False,
        "memory_exists_and_valid_json": False,
        "memory_has_min_new_entries": False,
        "memory_preserves_previous_entries": False,
        "handoff_yaml_exists_and_parses": False,
        "handoff_yaml_has_required_keys": False,
        "moltcaptcha_challenge_exists_and_parsable": False,
        "moltcaptcha_solution_exists": False,
        "moltcaptcha_solution_satisfies": False,
    }

    # Paths
    assessments_path = os.path.join(output_dir, "assessments.json")
    followups_path = os.path.join(output_dir, "followups.jsonl")
    memory_output_path = os.path.join(output_dir, "memory.json")
    memory_input_path = os.path.join(input_dir, "previous_memory.json")
    handoff_path = os.path.join(output_dir, "handoff_plan.yaml")
    molt_challenge_path = os.path.join(output_dir, "moltcaptcha_challenge.md")
    molt_solution_path = os.path.join(output_dir, "moltcaptcha_solution.txt")

    # 1) Assessments
    assessments = None
    if os.path.isfile(assessments_path):
        checks["assessments_exists"] = True
        data, err = read_json_file(assessments_path)
        if err is None and isinstance(data, list) and len(data) >= 4:
            checks["assessments_parse_and_len_ge4"] = True
            # Validate each item
            valid_all = True
            for item in data:
                if not isinstance(item, dict):
                    valid_all = False
                    break
                # Required fields
                required_status = {"Hot", "Warm", "Cold"}
                required_actions = {"pursue now", "qualify further", "nurture", "deprioritize"}
                # lead_id
                if "lead_id" not in item or not isinstance(item["lead_id"], str) or item["lead_id"] == "":
                    valid_all = False
                    break
                # status
                if item.get("status") not in required_status:
                    valid_all = False
                    break
                # scores
                for k in ("fit", "intent", "urgency", "authority"):
                    v = item.get(k)
                    if not is_int(v) or v < 0 or v > 10:
                        valid_all = False
                        break
                if not valid_all:
                    break
                # total_score equals sum
                s = item.get("total_score")
                if not is_int(s) or s != (item["fit"] + item["intent"] + item["urgency"] + item["authority"]):
                    valid_all = False
                    break
                # arrays
                if not isinstance(item.get("missing_info"), list):
                    valid_all = False
                    break
                if not isinstance(item.get("risks"), list):
                    valid_all = False
                    break
                # recommended_action
                if item.get("recommended_action") not in required_actions:
                    valid_all = False
                    break
                # reasoning length >= 40
                if not isinstance(item.get("reasoning"), str) or len(item["reasoning"]) < 40:
                    valid_all = False
                    break
            if valid_all:
                checks["assessments_items_valid"] = True
            assessments = data

    # 2) Followups
    followups_lines = None
    if os.path.isfile(followups_path):
        checks["followups_exists"] = True
        lines, err = parse_jsonl_lines(followups_path)
        if err is None and isinstance(lines, list):
            followups_lines = lines

    if assessments is not None and followups_lines is not None:
        # Required lead_ids with action pursue now or qualify further
        required_actions = {"pursue now", "qualify further"}
        required_leads = set()
        for it in assessments:
            if it.get("recommended_action") in required_actions:
                lid = it.get("lead_id")
                if isinstance(lid, str):
                    required_leads.add(lid)
        # Validate each line structure
        all_lines_struct_ok = True
        for obj in followups_lines:
            if not isinstance(obj, dict):
                all_lines_struct_ok = False
                break
            if not isinstance(obj.get("lead_id"), str):
                all_lines_struct_ok = False
                break
            subj = obj.get("subject")
            body = obj.get("body")
            if not isinstance(subj, str) or len(subj.strip()) == 0:
                all_lines_struct_ok = False
                break
            if not isinstance(body, str) or len(body) < 80:
                all_lines_struct_ok = False
                break
        # Check coverage: at least one entry per required lead_id
        coverage_ok = True
        for lid in required_leads:
            if not any(isinstance(o, dict) and o.get("lead_id") == lid for o in followups_lines):
                coverage_ok = False
                break
        if all_lines_struct_ok and coverage_ok:
            checks["followups_valid_for_required"] = True

    # 3) Memory
    memory_out = None
    if os.path.isfile(memory_output_path):
        data, err = read_json_file(memory_output_path)
        if err is None and isinstance(data, dict) and isinstance(data.get("entries"), list):
            checks["memory_exists_and_valid_json"] = True
            memory_out = data

    # New entries validation (>=4 entries meeting schema)
    if memory_out is not None:
        entries = memory_out.get("entries", [])
        valid_new = 0
        allowed_decisions = {"pursue now", "qualify further", "nurture", "deprioritize"}
        for e in entries:
            if not isinstance(e, dict):
                continue
            if not isinstance(e.get("lead_id"), str) or not e.get("lead_id"):
                continue
            if e.get("decision") not in allowed_decisions:
                continue
            kf = e.get("key_facts")
            tags = e.get("tags")
            if not isinstance(kf, list) or not (3 <= len(kf) <= 7):
                continue
            if not all(isinstance(x, str) and x.strip() for x in kf):
                continue
            if not isinstance(tags, list) or len(tags) < 1:
                continue
            if not all(isinstance(t, str) and t.strip() for t in tags):
                continue
            valid_new += 1
        if valid_new >= 4:
            checks["memory_has_min_new_entries"] = True

        # Preserve previous memory
        prev_data, prev_err = read_json_file(memory_input_path)
        if prev_err is None and isinstance(prev_data, dict) and isinstance(prev_data.get("entries"), list):
            prev_entries = prev_data.get("entries")
            out_entries = memory_out.get("entries", [])
            # Check that each prev entry dict is present in out entries (by deep equality)
            preserve_ok = True
            for pe in prev_entries:
                if not any((oe == pe) for oe in out_entries):
                    preserve_ok = False
                    break
            if preserve_ok:
                checks["memory_preserves_previous_entries"] = True
        else:
            # If previous memory file is missing or invalid, do not award this check
            pass

    # 4) Handoff plan YAML
    if os.path.isfile(handoff_path):
        text, err = read_text_file(handoff_path)
        if err is None:
            parsed = simple_yaml_parse(text)
            if isinstance(parsed, dict) and len(parsed) > 0:
                checks["handoff_yaml_exists_and_parses"] = True
                required_keys = ["target_agent", "handshake", "routing", "relay", "governance"]
                keys_ok = True
                for k in required_keys:
                    if k not in parsed:
                        keys_ok = False
                        break
                    v = parsed[k]
                    if isinstance(v, str):
                        if len(v.strip()) == 0:
                            keys_ok = False
                            break
                    elif isinstance(v, dict):
                        if len(v.keys()) == 0:
                            keys_ok = False
                            break
                    else:
                        # Unsupported type → fail
                        keys_ok = False
                        break
                if keys_ok:
                    checks["handoff_yaml_has_required_keys"] = True

    # 5) MoltCaptcha challenge and solution
    challenge_text = None
    if os.path.isfile(molt_challenge_path):
        ct, err = read_text_file(molt_challenge_path)
        if err is None and isinstance(ct, str) and len(ct.strip()) > 0:
            mentions_haiku, mentions_three, ascii_target, N = extract_moltcaptcha_requirements(ct)
            if mentions_haiku and mentions_three and isinstance(ascii_target, int) and (280 <= ascii_target <= 320) and isinstance(N, int) and N > 0:
                checks["moltcaptcha_challenge_exists_and_parsable"] = True
                challenge_text = ct

    if os.path.isfile(molt_solution_path):
        sol_text, err = read_text_file(molt_solution_path)
        if err is None and isinstance(sol_text, str):
            checks["moltcaptcha_solution_exists"] = True
            if checks["moltcaptcha_challenge_exists_and_parsable"]:
                _, _, ascii_target, N = extract_moltcaptcha_requirements(challenge_text)
                # Validate solution constraints
                # Must have exactly 3 non-empty lines
                lines = [ln.rstrip("\n") for ln in sol_text.splitlines()]
                # Remove trailing empty lines
                filtered = [ln for ln in lines if ln.strip() != ""]
                if len(filtered) == 3:
                    ascii_sum = first_char_ascii_sum(filtered)
                    total_words = count_words("\n".join(filtered))
                    if ascii_sum is not None and ascii_sum == ascii_target and total_words == N:
                        checks["moltcaptcha_solution_satisfies"] = True

    # Compute reward
    # Explicit no-op baseline: if output dir missing or all required artifacts absent, reward should be 0.0 naturally.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0
    # Ensure that if there are no output artifacts at all, reward is exactly 0.0
    if not os.path.isdir(output_dir):
        reward = 0.0

    # Print final result JSON (single line, reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()