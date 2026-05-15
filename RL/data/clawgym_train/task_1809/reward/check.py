import json
import os
import re
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def count_paragraphs(lines):
    paragraphs = 0
    in_para = False
    for line in lines:
        if line.strip() != "":
            if not in_para:
                paragraphs += 1
                in_para = True
        else:
            in_para = False
    return paragraphs

def find_line_index(lines, predicate):
    for i, line in enumerate(lines):
        if predicate(line):
            return i
    return None

def has_nonempty_content_after_label(lines, idx, labels_to_ignore=None):
    # Check same line after colon
    line = lines[idx]
    after_colon = ""
    if ":" in line:
        after_colon = line.split(":", 1)[1].strip()
    if after_colon:
        return True
    # Otherwise search subsequent non-empty line
    labels_to_ignore = set(labels_to_ignore or [])
    for j in range(idx + 1, len(lines)):
        candidate = lines[j].strip()
        if candidate == "":
            continue
        # If the next non-empty line is a label header, keep scanning but do not count it as content
        if any(candidate.startswith(lbl) for lbl in labels_to_ignore):
            return False
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Morning reflection checks
        "morning_file_exists": False,
        "morning_header_ok": False,
        "morning_reflection_section_present": False,
        "morning_reflection_paragraphs_count_ok": False,
        "morning_practical_application_present": False,
        "morning_closing_thought_present": False,
        "morning_quote_present": False,
        "morning_quote_author_valid": False,
        # Weekly summary checks
        "weekly_file_exists": False,
        "weekly_patterns_label_present": False,
        "weekly_virtue_ratings_label_present": False,
        "weekly_virtue_ratings_all_four_present": False,
        "weekly_best_moment_present": False,
        "weekly_hardest_moment_present": False,
        "weekly_focus_next_week_present": False,
        # Anxiety support checks
        "anxiety_file_exists": False,
        "anxiety_trigger_phrase_present": False,
        "anxiety_steps_in_order": False,
        "anxiety_virtue_filter_contains_all": False,
    }

    # Paths
    morning_path = os.path.join(output_dir, "morning_2026-04-17.txt")
    weekly_path = os.path.join(output_dir, "weekly_summary_2026-04-17.txt")
    anxiety_path = os.path.join(output_dir, "anxiety_support.txt")

    # Allowed authors for quote
    allowed_authors = ["Marcus Aurelius", "Epictetus", "Seneca", "Musonius Rufus", "Zeno of Citium"]

    # Morning reflection checks
    if os.path.isfile(morning_path):
        checks["morning_file_exists"] = True
        content = read_text_file(morning_path) or ""
        # Normalize newlines
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        lines = content.split("\n")
        if lines:
            # Handle possible BOM on the first line
            first_line = lines[0].lstrip("\ufeff")
            if first_line == "Affirmation ID: aff-035 (category: present)":
                checks["morning_header_ok"] = True

        # Reflection section present
        refl_idx = find_line_index(lines, lambda l: l.strip() == "Reflection:")
        if refl_idx is not None:
            checks["morning_reflection_section_present"] = True
            # Find Practical application line to delimit reflection section
            prac_idx = find_line_index(lines, lambda l: l.strip().startswith("Practical application:"))
            # Define slice for reflection paragraphs: lines after "Reflection:" up to just before "Practical application:"
            if prac_idx is None:
                # If Practical application not found, consider until end
                reflection_block = lines[refl_idx + 1 :]
            else:
                reflection_block = lines[refl_idx + 1 : prac_idx]
            # Count paragraphs (blank-line separated blocks of non-empty text)
            para_count = count_paragraphs(reflection_block)
            if para_count >= 2:
                checks["morning_reflection_paragraphs_count_ok"] = True

        # Practical application line present
        if any(l.strip().startswith("Practical application:") for l in lines):
            checks["morning_practical_application_present"] = True
        # Closing thought line present
        if any(l.strip().startswith("Closing thought:") for l in lines):
            checks["morning_closing_thought_present"] = True
        # Quote line present
        quote_line_idx = find_line_index(lines, lambda l: l.strip().startswith("Quote:"))
        if quote_line_idx is not None:
            checks["morning_quote_present"] = True
        # Quote author valid (appears on Quote line or anywhere in file)
        file_has_allowed_author = False
        # Check on Quote line if present
        candidate_lines = []
        if quote_line_idx is not None:
            candidate_lines.append(lines[quote_line_idx])
        # Also check entire file
        candidate_lines.extend(lines)
        for l in candidate_lines:
            for author in allowed_authors:
                if author in l:
                    file_has_allowed_author = True
                    break
            if file_has_allowed_author:
                break
        if file_has_allowed_author:
            checks["morning_quote_author_valid"] = True

    # Weekly summary checks
    if os.path.isfile(weekly_path):
        checks["weekly_file_exists"] = True
        wcontent = read_text_file(weekly_path) or ""
        wcontent = wcontent.replace("\r\n", "\n").replace("\r", "\n")
        wlines = wcontent.split("\n")

        # Patterns label present
        if any(l.strip().startswith("Patterns:") for l in wlines):
            checks["weekly_patterns_label_present"] = True

        # Virtue Ratings label present
        if any(l.strip().startswith("Virtue Ratings (1-5):") for l in wlines):
            checks["weekly_virtue_ratings_label_present"] = True

        # Virtue lines present (all four with 1-5)
        virtue_pattern = re.compile(r"^\s*(Wisdom|Justice|Temperance|Courage):\s*([1-5])\s*$")
        found_ratings = {}
        for l in wlines:
            m = virtue_pattern.match(l)
            if m:
                virtue = m.group(1)
                score = int(m.group(2))
                found_ratings[virtue] = score
        if all(v in found_ratings for v in ["Wisdom", "Justice", "Temperance", "Courage"]):
            checks["weekly_virtue_ratings_all_four_present"] = True

        # Best moment present with some non-empty text on same line or subsequent line
        labels_ignore = [
            "Patterns:",
            "Virtue Ratings (1-5):",
            "Best moment:",
            "Hardest moment:",
            "Focus for next week:",
        ]

        best_idx = find_line_index(wlines, lambda l: l.strip().startswith("Best moment:"))
        if best_idx is not None:
            if has_nonempty_content_after_label(wlines, best_idx, labels_to_ignore=labels_ignore):
                checks["weekly_best_moment_present"] = True

        hardest_idx = find_line_index(wlines, lambda l: l.strip().startswith("Hardest moment:"))
        if hardest_idx is not None:
            if has_nonempty_content_after_label(wlines, hardest_idx, labels_to_ignore=labels_ignore):
                checks["weekly_hardest_moment_present"] = True

        focus_idx = find_line_index(wlines, lambda l: l.strip().startswith("Focus for next week:"))
        if focus_idx is not None:
            if has_nonempty_content_after_label(wlines, focus_idx, labels_to_ignore=labels_ignore):
                checks["weekly_focus_next_week_present"] = True

    # Anxiety support checks
    if os.path.isfile(anxiety_path):
        checks["anxiety_file_exists"] = True
        acontent = read_text_file(anxiety_path) or ""
        acontent = acontent.replace("\r\n", "\n").replace("\r", "\n")
        alines = acontent.split("\n")
        atext = acontent

        # Trigger phrase present
        if "Trigger phrase: I need to stop" in atext:
            checks["anxiety_trigger_phrase_present"] = True

        # Steps in exact order and numbering
        headings = [
            "1) Acknowledge",
            "2) Breathe",
            "3) Ask",
            "4) Virtue filter",
            "5) Reframe",
            "6) Decide together",
        ]
        positions = []
        ok_order = True
        last_pos = -1
        for h in headings:
            pos = atext.find(h)
            if pos == -1:
                ok_order = False
                break
            if pos <= last_pos:
                ok_order = False
                break
            positions.append(pos)
            last_pos = pos
        if ok_order:
            checks["anxiety_steps_in_order"] = True

        # Virtue names under 4) Virtue filter
        if positions and len(positions) >= 4:
            start = positions[3]
            # End at next heading start if present, else end of file
            end = positions[4] if len(positions) > 4 else len(atext)
            virtue_section = atext[start:end]
            contains_all = all(name in virtue_section for name in ["Wisdom", "Justice", "Temperance", "Courage"])
            if contains_all:
                checks["anxiety_virtue_filter_contains_all"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    # Baseline: if no artifact exists in output or no check passes, reward must be 0.0
    # Our computation already yields 0.0 when nothing passes.

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()