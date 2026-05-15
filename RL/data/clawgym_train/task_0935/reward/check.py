import json
import os
import sys
import math
import re

def round_half_up(x):
    return int(math.floor(x + 0.5))

def count_words(text):
    return len(re.findall(r"\S+", text))

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_int_non_bool(value):
    return isinstance(value, int) and not isinstance(value, bool)

def find_headings(content, target):
    lines = content.splitlines()
    for ln in lines:
        s = ln.strip()
        if s.startswith("#"):
            # strip leading # and whitespace
            heading_text = s.lstrip("#").strip()
            if heading_text == target:
                return True
    return False

def section_text(content, section_name):
    """
    Return the text of a section starting at a heading line (case-sensitive match)
    until the next heading line or end of content.
    """
    lines = content.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("#"):
            htext = s.lstrip("#").strip()
            if htext == section_name:
                start_idx = i
                break
    if start_idx is None:
        return ""
    # find next heading after start_idx
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        sj = lines[j].strip()
        if sj.startswith("#"):
            end_idx = j
            break
    return "\n".join(lines[start_idx + 1:end_idx])

def compute_expected_stats(input_dir, output_daily_path):
    # Dates 2026-03-01 to 2026-03-08 inclusive
    base = "2026-03-"
    days = [f"{d:02d}" for d in range(1, 9)]
    total_words = 0
    days_written = 0
    for d in days:
        date_str = base + d
        input_path = os.path.join(input_dir, "journal", f"{date_str}.md")
        content = read_file(input_path)
        if content is not None:
            days_written += 1
            total_words += count_words(content)
        # include only today's new entry under output
        if date_str == "2026-03-08":
            out_content = read_file(output_daily_path)
            if out_content is not None:
                days_written += 1
                total_words += count_words(out_content)
    avg = round_half_up(total_words / days_written) if days_written > 0 else 0
    return days_written, total_words, avg

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "daily_exists": False,
        "daily_title_ok": False,
        "daily_prompt_valid": False,
        "daily_mood_header_ok": False,
        "daily_wordcount_80plus": False,
        "stats_exists": False,
        "stats_json_valid": False,
        "stats_keys_int": False,
        "stats_days_range_ok": False,
        "stats_avg_consistent": False,
        "stats_matches_expected": False,
        "weekly_reflection_exists": False,
        "weekly_title_ok": False,
        "weekly_sections_present": False,
        "weekly_mentions_weekdays": False,
        "weekly_suggestions_has_action_word_in_section": False,
    }

    # Paths
    daily_path = os.path.join(output_dir, "journal", "2026-03-08.md")
    stats_path = os.path.join(output_dir, "weekly", "2026-03-08_stats.json")
    weekly_reflection_path = os.path.join(output_dir, "weekly", "2026-03-01_to_2026-03-08.md")

    # Allowed prompts
    allowed_prompts = [
        "What was the highlight of your day?",
        "What was challenging today?",
        "What did you learn today?",
        "Name one thing you're grateful for.",
        "Describe today in three words.",
        "What are you looking forward to?",
        "What would you do differently today?",
        "Who made a positive impact on your day?",
        "What surprised you today?",
        "What's on your mind right now?"
    ]

    # Daily entry checks
    daily_content = read_file(daily_path)
    if daily_content is not None:
        checks["daily_exists"] = True
        # Title line starting with "# Journal — 2026-03-08"
        title_line_present = any(ln.strip().startswith("# Journal — 2026-03-08") for ln in daily_content.splitlines())
        if title_line_present:
            checks["daily_title_ok"] = True
        # Prompt line "Prompt: <prompt>" with valid prompt
        prompt_lines = [ln.strip() for ln in daily_content.splitlines() if ln.strip().startswith("Prompt: ")]
        if len(prompt_lines) >= 1:
            # Take first and verify exact prompt match
            pl = prompt_lines[0]
            prompt_value = pl[len("Prompt: "):].strip()
            if prompt_value in allowed_prompts:
                checks["daily_prompt_valid"] = True
        # Mood header line: starts with "## " and contains "Mood: Positive|Neutral|Negative"
        mood_ok = False
        for ln in daily_content.splitlines():
            s = ln.strip()
            if s.startswith("## "):
                if re.search(r"Mood:\s*(Positive|Neutral|Negative)\b", s):
                    mood_ok = True
                    break
        if mood_ok:
            checks["daily_mood_header_ok"] = True
        # Word count at least 80 across the whole file
        if count_words(daily_content) >= 80:
            checks["daily_wordcount_80plus"] = True

    # Weekly stats checks
    stats_data = None
    stats_content = read_file(stats_path)
    if stats_content is not None:
        checks["stats_exists"] = True
        stats_data = parse_json(stats_path)
        if isinstance(stats_data, dict):
            checks["stats_json_valid"] = True
            # keys present and integers
            has_keys = all(k in stats_data for k in ["daysWritten", "totalWords", "avgWords"])
            if has_keys and all(is_int_non_bool(stats_data[k]) for k in ["daysWritten", "totalWords", "avgWords"]):
                checks["stats_keys_int"] = True
                # daysWritten range check: 5 to 8 inclusive
                if 5 <= stats_data["daysWritten"] <= 8:
                    checks["stats_days_range_ok"] = True
                # avgWords consistent: rounded integer of totalWords/daysWritten
                if stats_data["daysWritten"] > 0:
                    expected_avg = round_half_up(stats_data["totalWords"] / stats_data["daysWritten"])
                    if stats_data["avgWords"] == expected_avg:
                        checks["stats_avg_consistent"] = True
                # matches expected computed from input + today's new entry
                exp_days, exp_total, exp_avg = compute_expected_stats(input_dir, daily_path)
                if (
                    stats_data["daysWritten"] == exp_days and
                    stats_data["totalWords"] == exp_total and
                    stats_data["avgWords"] == exp_avg
                ):
                    checks["stats_matches_expected"] = True

    # Weekly reflection checks
    weekly_content = read_file(weekly_reflection_path)
    if weekly_content is not None:
        checks["weekly_reflection_exists"] = True
        # Title exact line
        title_ok = any(ln.strip() == "Weekly Reflection (2026-03-01 to 2026-03-08)" for ln in weekly_content.splitlines())
        if title_ok:
            checks["weekly_title_ok"] = True
        # Sections present as headings
        sections_ok = all(find_headings(weekly_content, name) for name in ["Highlights", "Challenges", "Patterns & Trends", "Suggestions"])
        if sections_ok:
            checks["weekly_sections_present"] = True
        # Mention at least two weekday names anywhere
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        found = set()
        lower_content = weekly_content.lower()
        for wd in weekdays:
            if wd.lower() in lower_content:
                found.add(wd)
        if len(found) >= 2:
            checks["weekly_mentions_weekdays"] = True
        # Suggestions section contains at least one of: suggest, consider, recommend (case-insensitive)
        sugg_text = section_text(weekly_content, "Suggestions").lower()
        if any(term in sugg_text for term in ["suggest", "consider", "recommend"]):
            checks["weekly_suggestions_has_action_word_in_section"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if no expected output artifacts exist, reward must be 0.0
    any_outputs_exist = any(os.path.isfile(p) for p in [daily_path, stats_path, weekly_reflection_path])
    if not any_outputs_exist:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()