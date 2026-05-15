import json
import os
import sys
import re

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def split_words(text):
    # Count words by splitting on whitespace; consider alphanumerics and symbols
    return [w for w in re.split(r"\s+", text.strip()) if w]

def has_fenced_code_with_lang(lines, langs=("yaml", "bash")):
    starts = [f"```{l}" for l in langs]
    n = len(lines)
    for i, line in enumerate(lines):
        line_stripped = line.rstrip("\n")
        if any(line_stripped.startswith(s) for s in starts):
            # look for closing ```
            for j in range(i + 1, n):
                if lines[j].strip() == "```":
                    return True
    return False

def first_non_heading_chars_after_h1(text, limit=300):
    # After the first line (H1), concatenate subsequent lines that are not markdown headings (lines starting with '#')
    # Stop when reaching 'limit' characters
    lines = text.splitlines()
    if not lines:
        return ""
    # Remove possible BOM on first line
    lines[0] = lines[0].lstrip("\ufeff")
    after_h1 = lines[1:] if len(lines) > 1 else []
    buf = []
    total = 0
    for line in after_h1:
        if line.startswith("#"):  # treat as heading; skip
            continue
        # include the line with newline
        segment = (line + "\n")
        if total + len(segment) >= limit:
            remaining = limit - total
            buf.append(segment[:remaining])
            total += remaining
            break
        else:
            buf.append(segment)
            total += len(segment)
        if total >= limit:
            break
    return "".join(buf)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    blog_path = os.path.join(output_dir, "blog_post.md")
    sources_path = os.path.join(output_dir, "sources.json")
    checklist_path = os.path.join(output_dir, "checklist.md")

    checks = {
        "blog_exists": False,
        "h1_exact": False,
        "min_900_words": False,
        "has_h2_baseline": False,
        "has_h2_changes": False,
        "has_h2_results": False,
        "has_codeblock_yaml_or_bash": False,
        "contains_37_percent": False,
        "contains_18400": False,
        "no_banned_phrases": False,
        "concrete_early": False,
        "sources_exists": False,
        "sources_parseable": False,
        "sources_is_array": False,
        "sources_has_two_with_keys": False,
        "sources_has_37_percent_entry": False,
        "sources_has_18400_entry": False,
        "checklist_exists": False,
        "checklist_has_voice_match": False,
        "checklist_has_numbers_verified": False,
        "checklist_has_no_banned_phrases": False,
    }

    # Blog checks
    blog_text = None
    if os.path.isfile(blog_path):
        checks["blog_exists"] = True
        blog_text = read_file_text(blog_path)

    if blog_text is not None:
        # Normalize line endings
        lines = blog_text.splitlines()
        if lines:
            # handle BOM
            first_line = lines[0].lstrip("\ufeff")
            expected_h1 = "# How we cut our cloud bill by 37% without slowing down deploys"
            if first_line == expected_h1:
                checks["h1_exact"] = True

        # Word count
        word_count = len(split_words(blog_text))
        if word_count >= 900:
            checks["min_900_words"] = True

        # H2 exact headings as separate lines
        exact_h2s = {
            "## The baseline": "has_h2_baseline",
            "## What we changed": "has_h2_changes",
            "## The results (with numbers)": "has_h2_results",
        }
        for line in lines:
            stripped = line.rstrip()
            if stripped in exact_h2s:
                checks[exact_h2s[stripped]] = True

        # Fenced code block with yaml or bash
        if has_fenced_code_with_lang(lines, langs=("yaml", "bash")):
            checks["has_codeblock_yaml_or_bash"] = True

        # Contains required numbers
        if "37%" in blog_text:
            checks["contains_37_percent"] = True
        if "$18,400" in blog_text:
            checks["contains_18400"] = True

        # No banned phrases (case-insensitive substring match)
        banned_phrases = [
            "In today's",
            "Moreover",
            "Furthermore",
            "game-changer",
            "cutting-edge",
            "revolutionary",
        ]
        lower_text = blog_text.lower()
        banned_present = False
        for phrase in banned_phrases:
            if phrase.lower() in lower_text:
                banned_present = True
                break
        checks["no_banned_phrases"] = (not banned_present)

        # Concrete early in first 300 non-heading characters after H1
        early = first_non_heading_chars_after_h1(blog_text, limit=300)
        if early:
            if re.search(r"[0-9%$]", early) or "```" in early:
                checks["concrete_early"] = True

    # Sources checks
    sources_text = None
    if os.path.isfile(sources_path):
        checks["sources_exists"] = True
        sources_text = read_file_text(sources_path)

    sources_data = None
    if sources_text is not None:
        try:
            sources_data = json.loads(sources_text)
            checks["sources_parseable"] = True
            if isinstance(sources_data, list):
                checks["sources_is_array"] = True
                # Count objects with required keys
                count_with_keys = 0
                has_37 = False
                has_18400 = False
                for item in sources_data:
                    if isinstance(item, dict):
                        has_keys = all(k in item for k in ("value", "source", "quote"))
                        if has_keys:
                            count_with_keys += 1
                            # Specific entries
                            if item.get("value") == "37%" and item.get("source") == "input/notes.md":
                                if isinstance(item.get("quote"), str) and "37%" in item.get("quote"):
                                    has_37 = True
                            if item.get("value") == "$18,400" and item.get("source") == "input/notes.md":
                                if isinstance(item.get("quote"), str) and "$18,400" in item.get("quote"):
                                    has_18400 = True
                if count_with_keys >= 2:
                    checks["sources_has_two_with_keys"] = True
                if has_37:
                    checks["sources_has_37_percent_entry"] = True
                if has_18400:
                    checks["sources_has_18400_entry"] = True
        except Exception:
            pass

    # Checklist checks
    checklist_text = None
    if os.path.isfile(checklist_path):
        checks["checklist_exists"] = True
        checklist_text = read_file_text(checklist_path)

    if checklist_text is not None:
        lines = checklist_text.splitlines()
        low_lines = [ln.lower() for ln in lines]
        def has_phrase_line(phrase):
            p = phrase.lower()
            for ln in low_lines:
                if p in ln:
                    return True
            return False
        if has_phrase_line("Voice match"):
            checks["checklist_has_voice_match"] = True
        if has_phrase_line("Numbers verified"):
            checks["checklist_has_numbers_verified"] = True
        if has_phrase_line("No banned phrases"):
            checks["checklist_has_no_banned_phrases"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward between 0 and 1
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()