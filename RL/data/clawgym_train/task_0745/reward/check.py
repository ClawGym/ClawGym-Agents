import json
import os
import sys
import re

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def first_n_nonempty_lines(lines, n):
    return [ln for ln in lines if ln.strip()][:n]

def last_n_nonempty_lines(lines, n):
    nonempty = [ln for ln in lines if ln.strip()]
    return nonempty[-n:] if len(nonempty) >= n else nonempty

def strip_hook_number_prefix(s):
    return re.sub(r'^\s*\d+\.\s*', '', s).strip()

def contains_whole_word(text, word):
    return re.search(r'\b' + re.escape(word) + r'\b', text, flags=re.IGNORECASE) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Phase 1
        "phase1_exists": False,
        "phase1_non_empty": False,
        "phase1_questions_count_10_to_12": False,
        "phase1_validation_checklist_format": False,
        # Hooks
        "hooks_exists": False,
        "hooks_four_lines": False,
        "hooks_no_rhetorical_questions": False,
        "hooks_include_numbers": False,
        # Post
        "post_exists": False,
        "post_non_empty": False,
        "post_starts_with_chosen_hook_or_in_first3": False,
        "post_no_question_marks": False,
        "post_no_filler_words": False,
        "post_has_numeric_digit": False,
        "post_has_costly_signal": False,
        "post_directive_cta_with_story_near_end": False,
        "post_lines_within_140_chars": False,
    }

    # Phase 1 checks
    phase1_path = os.path.join(output_dir, "phase1_questions.txt")
    phase1_lines = read_text_lines(phase1_path)
    if phase1_lines is not None:
        checks["phase1_exists"] = True
        # Non-empty
        content_text = "\n".join(phase1_lines).strip()
        if content_text:
            checks["phase1_non_empty"] = True

            # Count numbered questions (lines starting with digit, period, space)
            question_lines = [ln for ln in phase1_lines if re.match(r'^\s*\d+\.\s+', ln)]
            if 10 <= len(question_lines) <= 12:
                checks["phase1_questions_count_10_to_12"] = True

            # Validation checklist block
            # Find the line "Validation checklist:" and verify next 4 lines
            idx = None
            for i, ln in enumerate(phase1_lines):
                if ln.strip() == "Validation checklist:":
                    idx = i
                    break
            if idx is not None:
                following = phase1_lines[idx + 1: idx + 5]
                if len(following) == 4:
                    v1 = following[0].strip() in ("- Metric: Yes", "- Metric: No")
                    v2 = following[1].strip() in ("- Insight: Yes", "- Insight: No")
                    v3 = following[2].strip() in ("- Mechanism: Yes", "- Mechanism: No")
                    v4 = following[3].strip() in ("- CTA: Yes", "- CTA: No")
                    if v1 and v2 and v3 and v4:
                        checks["phase1_validation_checklist_format"] = True

    # Hooks checks
    hooks_path = os.path.join(output_dir, "hooks.txt")
    hooks_lines = read_text_lines(hooks_path)
    nonempty_hooks = []
    if hooks_lines is not None:
        checks["hooks_exists"] = True
        nonempty_hooks = [ln for ln in hooks_lines if ln.strip()]
        if len(nonempty_hooks) == 4:
            checks["hooks_four_lines"] = True
            # No rhetorical questions: no '?' in any line
            if not any("?" in ln for ln in nonempty_hooks):
                checks["hooks_no_rhetorical_questions"] = True
            # At least one hook contains a digit
            if any(re.search(r'\d', ln) for ln in nonempty_hooks):
                checks["hooks_include_numbers"] = True

    # Post checks
    post_path = os.path.join(output_dir, "post.txt")
    post_lines = read_text_lines(post_path)
    if post_lines is not None:
        checks["post_exists"] = True
        post_text = "\n".join(post_lines)
        if post_text.strip():
            checks["post_non_empty"] = True

            # Line length <= 140 chars
            if all(len(ln) <= 140 for ln in post_lines):
                checks["post_lines_within_140_chars"] = True

            # No question marks anywhere
            if "?" not in post_text:
                checks["post_no_question_marks"] = True

            # No filler words (very, really, incredibly) as whole words, case-insensitive
            if not re.search(r'\b(very|really|incredibly)\b', post_text, flags=re.IGNORECASE):
                checks["post_no_filler_words"] = True

            # Has at least one numeric digit
            if re.search(r'\d', post_text):
                checks["post_has_numeric_digit"] = True

            # Costly signal: contains $ or € or word "hours"
            if ("$" in post_text) or ("€" in post_text) or contains_whole_word(post_text, "hours"):
                checks["post_has_costly_signal"] = True

            # Directive CTA near the end and includes STORY
            tail_lines = last_n_nonempty_lines(post_lines, 5)
            tail_joined = "\n".join(tail_lines).lower()
            directive_tokens = [
                "dm",
                "comment",
                "save this post",
                "message me",
                "book a call",
                "email me",
                "download",
            ]
            has_directive = any(tok in tail_joined for tok in directive_tokens)
            has_story = re.search(r'\bstory\b', "\n".join(tail_lines), flags=re.IGNORECASE) is not None
            if has_directive and has_story:
                checks["post_directive_cta_with_story_near_end"] = True

            # Starts with chosen hook or within first 3 non-empty lines
            chosen_index = None
            chosen_json = read_json(os.path.join(input_dir, "chosen_hook.json"))
            if chosen_json and isinstance(chosen_json, dict):
                idx_val = chosen_json.get("index")
                # Expect 1-based index
                if isinstance(idx_val, int) and 1 <= idx_val <= len(nonempty_hooks) if nonempty_hooks else False:
                    chosen_index = idx_val

            if chosen_index is not None and nonempty_hooks:
                hook_line = nonempty_hooks[chosen_index - 1].strip()
                hook_text_no_num = strip_hook_number_prefix(hook_line)
                first3 = first_n_nonempty_lines(post_lines, 3)
                # Check strict equality against any of the first 3 non-empty lines,
                # either with numbering prefix (verbatim line) or without numbering.
                def matches(line):
                    s = line.strip()
                    return s == hook_line or s == hook_text_no_num
                if any(matches(ln) for ln in first3):
                    checks["post_starts_with_chosen_hook_or_in_first3"] = True

    # Compute reward: proportion of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if passed_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()