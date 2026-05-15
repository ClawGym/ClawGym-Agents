import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def get_lines(text):
    return text.splitlines() if text is not None else []

def count_words(text):
    if not text:
        return 0
    return len(re.findall(r"\b\w+\b", text))

def find_first_nonempty_line(lines):
    for line in lines:
        if line.strip() != "":
            return line
    return None

def has_line_starting_with(lines, prefix):
    for line in lines:
        if line.startswith(prefix):
            return True
    return False

def count_occurrences(text, needle):
    return text.count(needle) if text else 0

def rapid_fire_host_count(lines):
    # Find RAPID FIRE section range
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## [RAPID FIRE]":
            start_idx = i + 1
            break
    if start_idx is None:
        return 0
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].startswith("## [") and lines[j].strip() != "## [RAPID FIRE]":
            end_idx = j
            break
    # Count lines beginning with **Host**:
    cnt = 0
    for k in range(start_idx, end_idx):
        line = lines[k]
        if line.startswith("**Host**:"):
            cnt += 1
    return cnt

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    script_path = os.path.join(output_dir, "script.md")
    desc_path = os.path.join(output_dir, "description.txt")

    checks = {
        "script_exists": False,
        "title_h1_first_line": False,
        "has_author_line": False,
        "has_duration_line": False,
        "has_opening_header": False,
        "has_min_3_topic_headers": False,
        "has_rapid_fire_header": False,
        "has_key_takeaways_header": False,
        "has_closing_header": False,
        "word_count_2400_3200": False,
        "min_10_host_labels": False,
        "min_10_guest_labels": False,
        "has_laughs_marker": False,
        "has_pause_or_thinking_marker": False,
        "has_well_actually": False,
        "has_i_never_thought_phrase": False,
        "rapid_fire_min3_host_lines": False,
        "description_exists": False,
        "description_single_paragraph_min40": False,
    }

    # Process script.md
    if os.path.isfile(script_path):
        checks["script_exists"] = True
        script_text = read_text(script_path)
        script_lines = get_lines(script_text)

        # First non-empty line begins with "# "
        first_line = find_first_nonempty_line(script_lines)
        if first_line is not None and first_line.startswith("# "):
            checks["title_h1_first_line"] = True

        # Presence of "**Author**:" and "**Duration**:"
        checks["has_author_line"] = any(re.match(r"^\*\*Author\*\*:\s*", line) for line in script_lines)
        checks["has_duration_line"] = any(re.match(r"^\*\*Duration\*\*:\s*", line) for line in script_lines)

        # Section headers
        checks["has_opening_header"] = "## [OPENING]" in script_text.splitlines()
        # Topics: at least three topic headers
        topic_headers = [line for line in script_lines if re.match(r"^## \[TOPIC \d+\]", line)]
        if len(topic_headers) >= 3:
            checks["has_min_3_topic_headers"] = True
        checks["has_rapid_fire_header"] = has_line_starting_with(script_lines, "## [RAPID FIRE]")
        checks["has_key_takeaways_header"] = has_line_starting_with(script_lines, "## [KEY TAKEAWAYS]")
        checks["has_closing_header"] = has_line_starting_with(script_lines, "## [CLOSING]")

        # Word count
        wc = count_words(script_text)
        if 2400 <= wc <= 3200:
            checks["word_count_2400_3200"] = True

        # Speaker labels counts
        if count_occurrences(script_text, "**Host**:") >= 10:
            checks["min_10_host_labels"] = True
        if count_occurrences(script_text, "**Guest**:") >= 10:
            checks["min_10_guest_labels"] = True

        # Markers presence (case-sensitive for markers)
        if "[laughs]" in script_text:
            checks["has_laughs_marker"] = True
        if ("[pause]" in script_text) or ("[thinking]" in script_text):
            checks["has_pause_or_thinking_marker"] = True

        # Phrases presence (case-insensitive)
        low = script_text.lower()
        if "well, actually" in low:
            checks["has_well_actually"] = True
        if "i never thought of it that way" in low:
            checks["has_i_never_thought_phrase"] = True

        # RAPID FIRE host lines
        rf_host_count = rapid_fire_host_count(script_lines)
        if rf_host_count >= 3:
            checks["rapid_fire_min3_host_lines"] = True

    # Process description.txt
    if os.path.isfile(desc_path):
        checks["description_exists"] = True
        desc_text = read_text(desc_path) or ""
        # Single paragraph: no blank lines
        lines = desc_text.splitlines()
        has_blank_line = any(l.strip() == "" for l in lines)
        wc_desc = count_words(desc_text)
        if (not has_blank_line) and wc_desc >= 40 and desc_text.strip() != "":
            checks["description_single_paragraph_min40"] = True

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # Ensure baseline: if no outputs exist, reward is 0.0
    output_exists = checks["script_exists"] or checks["description_exists"]
    if not output_exists:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()