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

def word_tokens(s):
    if s is None:
        return []
    return [t for t in re.split(r"\s+", s.strip()) if t]

def has_unescaped_specials(s):
    # Return True if any unescaped %, _ or & exists (i.e., appears not preceded by backslash)
    if s is None:
        return True
    specials = {'%', '_', '&'}
    prev = ''
    for ch in s:
        if ch in specials:
            if prev != '\\':
                return True
        prev = ch
    return False

def contains_emdash(s):
    if s is None:
        return False
    return '—' in s

def contains_itemize_line(s):
    if s is None:
        return False
    for line in s.splitlines():
        if "\\item" in line:
            return True
    return False

def deai_phrases_absent(s):
    if s is None:
        return False
    # Case-insensitive absence of listed phrases
    bad_phrases = [
        "furthermore",
        "moreover",
        "it is worth noting that",
        "in summary",
        "as can be seen",
    ]
    low = s.lower()
    return not any(bp in low for bp in bad_phrases)

def caption_starts_with_textbf_and_brace(s):
    if s is None:
        return False, False
    stripped = s.lstrip()
    starts = stripped.startswith("\\textbf{")
    has_closing = False
    if starts:
        close_idx = stripped.find("}")
        has_closing = close_idx != -1
    return starts, has_closing

def contains_han(s):
    if not isinstance(s, str):
        return False
    return re.search(r"[\u4e00-\u9fff]", s) is not None

def count_numbered_questions(s):
    if s is None:
        return 0
    count = 0
    for line in s.splitlines():
        if re.match(r"^\s*\d+\.\s", line):
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dict: all False until proven True
    checks = {
        # Existence checks
        "has_condensed": False,
        "has_expanded": False,
        "has_polished": False,
        "has_backtranslations": False,
        "has_review": False,
        "has_caption": False,

        # Word delta checks
        "condensed_word_delta_ok": False,
        "expanded_word_delta_ok": False,

        # Style checks (no em-dash)
        "condensed_no_emdash": False,
        "expanded_no_emdash": False,
        "polished_no_emdash": False,

        # Style checks (no \\item)
        "condensed_no_itemize": False,
        "expanded_no_itemize": False,
        "polished_no_itemize": False,

        # LaTeX special chars escaped
        "condensed_latex_escaped": False,
        "expanded_latex_escaped": False,
        "polished_latex_escaped": False,

        # De-AI phrases absent in polished
        "polished_deai_phrases_absent": False,

        # Backtranslations JSON checks
        "backtranslations_valid_keys": False,
        "backtranslations_values_chinese": False,

        # Review structure checks
        "review_has_sections": False,
        "review_questions_3_to_5": False,

        # Caption checks
        "caption_starts_with_textbf": False,
        "caption_has_closing_brace": False,
        "caption_word_count_ok": False,
        "caption_no_markdown_bold": False,
    }

    # Paths
    input_paper_path = os.path.join(input_dir, "paper_section.txt")
    input_figure_desc_path = os.path.join(input_dir, "figure_desc.txt")

    condensed_path = os.path.join(output_dir, "condensed.txt")
    expanded_path = os.path.join(output_dir, "expanded.txt")
    polished_path = os.path.join(output_dir, "polished.txt")
    backtranslations_path = os.path.join(output_dir, "backtranslations.json")
    review_path = os.path.join(output_dir, "review.md")
    caption_path = os.path.join(output_dir, "caption.txt")

    # Read input reference
    input_paper_text = read_text(input_paper_path)
    input_tokens = word_tokens(input_paper_text)

    # 1) Existence and content reads
    condensed_text = read_text(condensed_path)
    if condensed_text is not None:
        checks["has_condensed"] = True

    expanded_text = read_text(expanded_path)
    if expanded_text is not None:
        checks["has_expanded"] = True

    polished_text = read_text(polished_path)
    if polished_text is not None:
        checks["has_polished"] = True

    review_text = read_text(review_path)
    if review_text is not None:
        checks["has_review"] = True

    caption_text = read_text(caption_path)
    if caption_text is not None:
        checks["has_caption"] = True

    # backtranslations JSON
    backtranslations_text = read_text(backtranslations_path)
    backtranslations_obj = None
    if backtranslations_text is not None:
        try:
            backtranslations_obj = json.loads(backtranslations_text)
            checks["has_backtranslations"] = True
        except Exception:
            checks["has_backtranslations"] = False
            backtranslations_obj = None

    # 2) Word-count deltas
    if checks["has_condensed"] and input_tokens:
        cond_tokens = word_tokens(condensed_text)
        delta = len(input_tokens) - len(cond_tokens)
        if 5 <= delta <= 15:
            checks["condensed_word_delta_ok"] = True

    if checks["has_expanded"] and input_tokens:
        exp_tokens = word_tokens(expanded_text)
        delta = len(exp_tokens) - len(input_tokens)
        if 5 <= delta <= 15:
            checks["expanded_word_delta_ok"] = True

    # 3) Style constraints for three text outputs
    # No em-dash
    if checks["has_condensed"] and not contains_emdash(condensed_text):
        checks["condensed_no_emdash"] = True
    if checks["has_expanded"] and not contains_emdash(expanded_text):
        checks["expanded_no_emdash"] = True
    if checks["has_polished"] and not contains_emdash(polished_text):
        checks["polished_no_emdash"] = True

    # No \item
    if checks["has_condensed"] and not contains_itemize_line(condensed_text):
        checks["condensed_no_itemize"] = True
    if checks["has_expanded"] and not contains_itemize_line(expanded_text):
        checks["expanded_no_itemize"] = True
    if checks["has_polished"] and not contains_itemize_line(polished_text):
        checks["polished_no_itemize"] = True

    # LaTeX special characters escaped
    if checks["has_condensed"] and not has_unescaped_specials(condensed_text):
        checks["condensed_latex_escaped"] = True
    if checks["has_expanded"] and not has_unescaped_specials(expanded_text):
        checks["expanded_latex_escaped"] = True
    if checks["has_polished"] and not has_unescaped_specials(polished_text):
        checks["polished_latex_escaped"] = True

    # 4) De-AI phrases absence in polished
    if checks["has_polished"] and deai_phrases_absent(polished_text):
        checks["polished_deai_phrases_absent"] = True

    # 5) backtranslations.json structure and Chinese chars
    if backtranslations_obj is not None and isinstance(backtranslations_obj, dict):
        required_keys = ["condensed_zh", "expanded_zh", "polished_zh"]
        if all(k in backtranslations_obj and isinstance(backtranslations_obj.get(k), str) for k in required_keys):
            checks["backtranslations_valid_keys"] = True
            # values must be non-empty strings with at least one Han character
            values_ok = True
            for k in required_keys:
                v = backtranslations_obj.get(k, "")
                if not v.strip() or not contains_han(v):
                    values_ok = False
                    break
            if values_ok:
                checks["backtranslations_values_chinese"] = True

    # 6) review.md structure
    if checks["has_review"]:
        low = review_text.lower()
        required_sections = ["summary", "strengths", "weaknesses", "questions", "preliminary score:"]
        if all(sec in low for sec in required_sections):
            checks["review_has_sections"] = True

        q_count = count_numbered_questions(review_text)
        if 3 <= q_count <= 5:
            checks["review_questions_3_to_5"] = True

    # 7) caption.txt constraints
    if checks["has_caption"]:
        starts, has_close = caption_starts_with_textbf_and_brace(caption_text)
        if starts:
            checks["caption_starts_with_textbf"] = True
        if has_close:
            checks["caption_has_closing_brace"] = True
        # word count
        cap_tokens = word_tokens(caption_text)
        if len(cap_tokens) <= 80 and len(cap_tokens) > 0:
            checks["caption_word_count_ok"] = True
        # no markdown bold **
        if "**" not in caption_text:
            checks["caption_no_markdown_bold"] = True

    # Compute reward as fraction of passed checks
    # Only checks that depend on output/ artifacts contribute; all defined checks do.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure baseline: if no outputs exist (none of the has_* True), reward must be 0.0
    has_any_output = any(checks[k] for k in ["has_condensed", "has_expanded", "has_polished", "has_backtranslations", "has_review", "has_caption"])
    if not has_any_output:
        reward = 0.0

    # Clamp reward to [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()