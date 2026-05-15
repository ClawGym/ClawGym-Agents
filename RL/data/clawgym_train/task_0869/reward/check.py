import json
import os
import re
import sys

def read_lines_preserve_spaces(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            # splitlines() removes newline characters but preserves other spaces
            return f.read().splitlines()
    except Exception:
        return None

def parse_keywords(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return []
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    titles_path = os.path.join(output_dir, "titles.txt")
    keywords_path = os.path.join(input_dir, "keywords.txt")

    checks = {
        "file_exists": False,
        "exactly_seven_lines": False,
        "numbering_correct_order": False,
        "numbering_format_strict": False,
        "length_range_all": False,
        "includes_all_keywords": False,
        "has_how_start": False,
        "has_guide_anywhere": False,
        "has_digit_listicle": False,
        "has_power_words_two_titles": False,
    }

    lines = read_lines_preserve_spaces(titles_path)
    if lines is None:
        # No output file; all checks remain False
        result = {"reward": 0.0, **checks}
        print(json.dumps(result))
        return

    checks["file_exists"] = True

    # Exactly 7 non-empty lines
    if len(lines) == 7 and all(l.strip() != "" for l in lines):
        checks["exactly_seven_lines"] = True

    # Numbering correct order and numbering format strict
    correct_order = True
    strict_format = True
    numbering_re = re.compile(r"^[1-7]\.\s")
    for idx, line in enumerate(lines, start=1):
        if not line.startswith(f"{idx}. "):
            correct_order = False
        if not numbering_re.match(line):
            strict_format = False
    checks["numbering_correct_order"] = correct_order
    checks["numbering_format_strict"] = strict_format

    # Length range 50-60 inclusive (including numbering)
    if all(50 <= len(line) <= 60 for line in lines):
        checks["length_range_all"] = True

    # Prepare content after numbering "N. "
    contents = []
    for line in lines:
        if numbering_re.match(line):
            contents.append(line[3:])
        else:
            contents.append("")  # placeholder to avoid index errors later

    # Includes all keywords from input/keywords.txt (case-insensitive substring)
    keywords = parse_keywords(keywords_path)
    def contains_all_keywords(text):
        tl = text.lower()
        for kw in keywords:
            if kw.lower() not in tl:
                return False
        return True
    if checks["file_exists"]:
        if all(contains_all_keywords(c) for c in contents):
            checks["includes_all_keywords"] = True

    # Variety checks after removing numbering
    # At least one title starts with "How" (case-insensitive)
    if any(c.lstrip().lower().startswith("how") for c in contents):
        checks["has_how_start"] = True

    # At least one title contains the word "Guide" (case-insensitive)
    if any(re.search(r"\bguide\b", c, flags=re.IGNORECASE) for c in contents):
        checks["has_guide_anywhere"] = True

    # At least one title starts with a digit after numbering
    if any((c.lstrip()[:1].isdigit()) for c in contents if c is not None):
        checks["has_digit_listicle"] = True

    # At least two titles include at least one power word (Ultimate, Complete, Essential, Proven)
    power_re = re.compile(r"\b(ultimate|complete|essential|proven)\b", flags=re.IGNORECASE)
    power_count = sum(1 for c in contents if power_re.search(c or ""))
    if power_count >= 2:
        checks["has_power_words_two_titles"] = True

    # Compute reward: all-or-nothing
    all_pass = all(checks.values())
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()