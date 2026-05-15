import json
import os
import sys
import re

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def starts_with_list_marker(line):
    s = line.lstrip()
    if s.startswith("-") or s.startswith("*"):
        return True
    # number followed by a period, e.g., "1." or "12."
    if len(s) >= 2 and s[0].isdigit() and s[1] == ".":
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    outline_path = os.path.join(output_dir, "ministry_outline.json")
    checklist_path = os.path.join(output_dir, "checklist.txt")
    verses_path = os.path.join(input_dir, "verses.json")

    checks = {
        "json_exists_and_parses": False,
        "required_fields_present": False,
        "scripture_paragraph_jn14_28_col1_15_verbatim": False,
        "additional_two_verses_in_reasoning_reason_illustration": False,
        "jehovah_mentioned_twice": False,
        "no_lists_in_text": False,
        "no_urls_in_text": False,
        "checklist_file_ok": False,
    }

    outline = None
    if os.path.isfile(outline_path):
        outline = load_json(outline_path)
        if isinstance(outline, dict):
            checks["json_exists_and_parses"] = True

    # If JSON not present/parsed, baseline reward must be 0
    # Still evaluate other checks only if outline exists
    verses = None
    if os.path.isfile(verses_path):
        verses = load_json(verses_path)

    required_fields = [
        "question",
        "key_idea",
        "reasoning_acknowledge",
        "reasoning_scripture",
        "reasoning_reason_illustration",
        "reasoning_conclusion",
    ]

    # Collect content for global text rules
    combined_text = ""

    if checks["json_exists_and_parses"]:
        # Required fields non-empty strings
        has_all = True
        for k in required_fields:
            if k not in outline:
                has_all = False
                break
            v = outline.get(k)
            if not isinstance(v, str) or len(v.strip()) == 0:
                has_all = False
                break
        checks["required_fields_present"] = has_all

        # Build combined text
        combined_text = "\n".join([outline.get(k, "") for k in required_fields if isinstance(outline.get(k, ""), str)])

        # Scripture paragraph must include exact John 14:28 and Colossians 1:15, verbatim, inside a single flowing paragraph
        rs = outline.get("reasoning_scripture", "")
        scripture_ok = False
        if isinstance(rs, str) and rs.strip() and verses and isinstance(verses, dict):
            jn1428 = verses.get("John 14:28")
            col115 = verses.get("Colossians 1:15")
            if isinstance(jn1428, str) and isinstance(col115, str):
                # exact substring match
                has_john = jn1428 in rs
                has_col = col115 in rs
                # single flowing paragraph: no newline characters
                single_para = ("\n" not in rs and "\r" not in rs)
                scripture_ok = has_john and has_col and single_para
        checks["scripture_paragraph_jn14_28_col1_15_verbatim"] = scripture_ok

        # reasoning_reason_illustration must include at least two additional distinct exact verse strings from allowed set
        rri = outline.get("reasoning_reason_illustration", "")
        addl_ok = False
        if isinstance(rri, str) and rri.strip() and verses and isinstance(verses, dict):
            allowed_keys = ["1 Corinthians 11:3", "John 17:3", "Acts 2:36", "Proverbs 8:22"]
            present_count = 0
            seen = set()
            for k in allowed_keys:
                txt = verses.get(k)
                if isinstance(txt, str) and txt in rri:
                    present_count += 1
                    seen.add(k)
            addl_ok = present_count >= 2
        checks["additional_two_verses_in_reasoning_reason_illustration"] = addl_ok

        # Jehovah mentioned at least twice across the outline
        jehovah_count = combined_text.count("Jehovah")
        checks["jehovah_mentioned_twice"] = jehovah_count >= 2

        # No bullets/numbered lists anywhere in the JSON text
        no_lists = True
        for line in combined_text.splitlines():
            if starts_with_list_marker(line):
                no_lists = False
                break
        checks["no_lists_in_text"] = no_lists

        # No URLs
        has_http = ("http://" in combined_text) or ("https://" in combined_text)
        checks["no_urls_in_text"] = not has_http

    # Checklist file check
    if os.path.isfile(checklist_path):
        content = read_text(checklist_path) or ""
        count_ok_lines = sum(1 for line in content.splitlines() if line.startswith("OK:"))
        checks["checklist_file_ok"] = count_ok_lines >= 5

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Reward: if core JSON artifact missing/invalid, reward = 0.0
    if not checks["json_exists_and_parses"]:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()