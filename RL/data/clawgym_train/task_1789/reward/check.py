import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def extract_section(text, header_label):
    # Return the content lines between a header line equal to header_label and the next '## [' header or EOF
    lines = text.splitlines()
    content_lines = []
    in_section = False
    for i, line in enumerate(lines):
        if in_section:
            if line.strip().startswith("## [") and line.strip() != header_label:
                break
            else:
                content_lines.append(line)
        else:
            if line.strip() == header_label:
                in_section = True
    # Trim leading/trailing blank lines
    while content_lines and content_lines[0].strip() == "":
        content_lines.pop(0)
    while content_lines and content_lines[-1].strip() == "":
        content_lines.pop()
    return "\n".join(content_lines)

def count_words(s):
    # Count words by splitting on whitespace after stripping
    return len([w for w in re.split(r"\s+", s.strip()) if w])

def last_nonempty_line(text):
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "podcast_exists": False,
        "json_exists": False,
        "title_line_ok": False,
        "author_line_ok": False,
        "duration_line_ok": False,
        "computed_duration_ok": False,
        "style_line_ok": False,
        "headings_ok": False,
        "hook_verbatim_ok": False,
        "key_ideas_ok": False,
        "synthesis_ok": False,
        "pauses_ok": False,
        "closing_note_ok": False,
        "json_fields_ok": False,
        "json_keyideas_ok": False,
        "json_summary_verbatim_ok": False
    }

    # Load input reference
    input_path = os.path.join(input_dir, "book.json")
    book = read_json(input_path)
    title = None
    author = None
    summary = None
    if isinstance(book, dict):
        title = book.get("title")
        author = book.get("author")
        summary = book.get("summary")

    # Known expected sentences for this dataset (1st, 4th, 7th)
    expected_ki_sentences = [
        "Many professionals struggle to find time for deep, focused work in a world of constant distraction.",
        "By scheduling blocks of deep work and protecting them, you can produce at an elite level.",
        "Embracing boredom and quitting social media that fails a strict cost-benefit test removes attention drains."
    ]

    # Compute expected duration from the three key idea sentences at 150 wpm, minimum 5 minutes
    total_words = sum(count_words(s) for s in expected_ki_sentences)
    computed_minutes = (total_words + 150 - 1) // 150  # ceil
    if computed_minutes < 5:
        computed_minutes = 5
    expected_duration_token = f"**Duration**: ~{computed_minutes} minutes"

    # Load outputs
    podcast_path = os.path.join(output_dir, "podcast.md")
    text_json_path = os.path.join(output_dir, "text_summary.json")

    podcast_text = read_text(podcast_path)
    if isinstance(podcast_text, str):
        checks["podcast_exists"] = True

    text_summary = read_json(text_json_path)
    if isinstance(text_summary, dict):
        checks["json_exists"] = True

    # Validate podcast.md
    if checks["podcast_exists"]:
        # Title line check: top non-empty line contains title and "Summary Podcast Script"
        first_lines = [ln for ln in podcast_text.splitlines() if ln.strip()]
        if first_lines:
            top_line = first_lines[0]
            if (title is not None and "Summary Podcast Script" in top_line and str(title) in top_line):
                checks["title_line_ok"] = True

        # Metadata checks
        if author is not None and f"**Author**: {author}" in podcast_text:
            checks["author_line_ok"] = True
        if expected_duration_token in podcast_text:
            checks["duration_line_ok"] = True
        # Style exact token without bold as required
        if "Style: Single narrator, summary format" in podcast_text:
            checks["style_line_ok"] = True

        # Headings presence
        required_headings = [
            "## [HOOK]",
            "## [INTRO]",
            "## [KEY IDEA 1]",
            "## [KEY IDEA 2]",
            "## [KEY IDEA 3]",
            "## [SYNTHESIS]",
            "## [CALL TO ACTION]"
        ]
        if all(h in podcast_text for h in required_headings):
            checks["headings_ok"] = True

        # HOOK verbatim content (must equal full summary text)
        if summary is not None:
            hook_content = extract_section(podcast_text, "## [HOOK]")
            # Stop at [pause] if present
            if "[pause]" in hook_content:
                hook_content = hook_content.split("[pause]")[0].strip()
            if hook_content.strip() == summary.strip():
                checks["hook_verbatim_ok"] = True

        # Key ideas content and takeaway lines
        ki_ok = True
        for idx, sent in enumerate(expected_ki_sentences, start=1):
            section = extract_section(podcast_text, f"## [KEY IDEA {idx}]")
            if not section:
                ki_ok = False
                break
            # Must contain sentence as content
            if sent not in section:
                ki_ok = False
                break
            # Must contain Takeaway line exactly matching required format
            expected_takeaway_line = f"Takeaway: Apply this insight: {sent}"
            # Look for exact line match or presence in section text with line boundaries
            found_line = False
            for ln in section.splitlines():
                if ln.strip() == expected_takeaway_line:
                    found_line = True
                    break
            if not found_line:
                ki_ok = False
                break
        if ki_ok:
            checks["key_ideas_ok"] = True

        # Synthesis: must restate full summary with the required prefix
        if summary is not None:
            synthesis_section = extract_section(podcast_text, "## [SYNTHESIS]")
            expected_synthesis_snippet = f"These ideas work together to show that {summary}"
            if expected_synthesis_snippet in synthesis_section:
                checks["synthesis_ok"] = True

        # Pauses: ensure [pause] appears between sections (at least after HOOK, INTRO, KI1, KI2, KI3, SYNTHESIS)
        pause_count = podcast_text.count("[pause]")
        if pause_count >= 6:
            checks["pauses_ok"] = True

        # Closing note: final italicized acknowledgment, e.g., contains "Summary generated" at end
        last_line = last_nonempty_line(podcast_text)
        if "Summary generated" in last_line:
            checks["closing_note_ok"] = True

        # Duration computed consistency
        if checks["duration_line_ok"]:
            if expected_duration_token in podcast_text:
                checks["computed_duration_ok"] = True

    # Validate text_summary.json
    if checks["json_exists"]:
        jf = text_summary
        fields_ok = True
        if jf.get("title") != title:
            fields_ok = False
        if jf.get("author") != author:
            fields_ok = False
        if jf.get("format") != "text":
            fields_ok = False
        if not isinstance(jf.get("key_ideas"), list) or len(jf.get("key_ideas")) != 3:
            fields_ok = False
        if fields_ok:
            checks["json_fields_ok"] = True

        # Summary verbatim check
        if summary is not None and isinstance(jf.get("summary"), str) and jf.get("summary") == summary:
            checks["json_summary_verbatim_ok"] = True

        # Key ideas exact content and takeaway
        ki_json_ok = True
        if isinstance(jf.get("key_ideas"), list) and len(jf.get("key_ideas")) == 3:
            for i, item in enumerate(jf["key_ideas"], start=1):
                if not isinstance(item, dict):
                    ki_json_ok = False
                    break
                expected_title = f"Key Idea {i}"
                expected_content = expected_ki_sentences[i-1]
                expected_takeaway = f"Apply this insight: {expected_content}"
                if item.get("title") != expected_title:
                    ki_json_ok = False
                    break
                if item.get("content") != expected_content:
                    ki_json_ok = False
                    break
                if item.get("takeaway") != expected_takeaway:
                    ki_json_ok = False
                    break
        else:
            ki_json_ok = False

        if ki_json_ok:
            checks["json_keyideas_ok"] = True

    # Compute reward as fraction of passed checks.
    # Ensure no-op baseline -> 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    # Print JSON result
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()