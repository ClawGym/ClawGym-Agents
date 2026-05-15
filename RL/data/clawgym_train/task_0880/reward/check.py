import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def lines(text):
    return text.splitlines()

def find_heading(lines_list, heading_text):
    # Accept headings with optional Markdown '#' markers
    for ln in lines_list:
        s = ln.lstrip()
        # Strip leading '#' and spaces
        s2 = s.lstrip("#").lstrip()
        if s2 == heading_text:
            return True
    return False

def contains_exact_bullet(lines_list, text):
    # Must be exact bullet line: "- " + text
    target = f"- {text}"
    return any(ln.strip() == target for ln in lines_list)

def contains_exact_line(lines_list, text):
    # Exact line match ignoring surrounding whitespace
    return any(ln.strip() == text for ln in lines_list)

def split_body_and_hashtags(text):
    # Identify bottom block containing any '#' characters
    # We consider any line containing a '#' character as part of the hashtag block at the end.
    # Body is all content before the first line that contains '#' in the bottom-most region.
    all_lines = lines(text)
    if not any('#' in ln for ln in all_lines):
        return text, ""  # no hashtags
    # Find the first index from the end that contains '#'
    # Then include all consecutive lines upward that contain '#'? We define the block as all lines
    # from the earliest occurrence among lines that contain '#', provided no later non-hashtag body content follows.
    # Robust approach: Find the first index from top that contains '#', ensure no '#' before body end.
    # But to keep it safe and aligned with "final lines": find the first hashtag line such that all lines after it contain at least one '#'.
    idx_first_hashtag_in_tail = None
    for i in range(len(all_lines)):
        if '#' in all_lines[i]:
            # Check if any earlier line after this index has no '#'
            # We require that there is no non-hashtag line after the first hashtag line (except blank lines)
            tail = all_lines[i:]
            if all(('#' in t or t.strip() == "") for t in tail):
                idx_first_hashtag_in_tail = i
                break
    if idx_first_hashtag_in_tail is None:
        # If we cannot confidently identify a clean tail block, treat entire content as body to enforce stricter checks
        return text, ""
    body_text = "\n".join(all_lines[:idx_first_hashtag_in_tail]).rstrip("\n")
    tags_text = "\n".join(all_lines[idx_first_hashtag_in_tail:]).rstrip("\n")
    return body_text, tags_text

def get_paragraphs(body_text):
    # Paragraphs are groups of non-empty lines separated by at least one blank line
    paras = []
    current = []
    for ln in body_text.splitlines():
        if ln.strip() == "":
            if current:
                paras.append("\n".join(current).strip())
                current = []
        else:
            current.append(ln)
    if current:
        paras.append("\n".join(current).strip())
    return paras

def sentence_endings_count(text):
    # Count occurrences of ., !, ? as sentence enders
    return text.count('.') + text.count('!') + text.count('?')

def last_non_empty_line(text):
    for ln in reversed(text.splitlines()):
        if ln.strip() != "":
            return ln
    return ""

def has_first_person(text):
    # Look for 'I' or 'we' as standalone words (case-insensitive)
    return re.search(r'\b(i|we)\b', text, flags=re.IGNORECASE) is not None

def has_contraction(text):
    # Any ASCII apostrophe within a word
    return re.search(r"\b\w+'\w+\b", text) is not None

def buzzwords_absent(text):
    banned = ["synergy", "leverage", "ecosystem", "disrupt", "game-changer"]
    lower = text.lower()
    return not any(b in lower for b in banned)

def hashtags_check(full_text):
    # Returns (ok, count, only_bottom)
    # ok: no hashtags, or all hashtags are confined to a clean tail block and total count <=5
    # only_bottom: True if hashtags (if any) only appear at bottom, False otherwise
    body, tags = split_body_and_hashtags(full_text)
    count_total = full_text.count('#')
    if count_total == 0:
        return True, 0, True
    # Ensure no '#' in body
    if '#' in body:
        return False, count_total, False
    # Count hashtags in tags block and ensure number <=5
    if count_total <= 5:
        return True, count_total, True
    return False, count_total, True

def validate_credibility_report_shape(obj):
    # Must have "claims" (list) and "summary" (dict with overall_assessment string)
    if not isinstance(obj, dict):
        return False
    if "claims" not in obj or "summary" not in obj:
        return False
    claims = obj["claims"]
    summary = obj["summary"]
    if not isinstance(claims, list) or not isinstance(summary, dict):
        return False
    if "overall_assessment" not in summary or not isinstance(summary["overall_assessment"], str):
        return False
    # Validate each claim item
    allowed_analysis = {"factual", "opinion", "web"}
    allowed_source = {"A+", "A", "B+", "B", "C", "D"}
    for item in claims:
        if not isinstance(item, dict):
            return False
        required_keys = [
            "claim", "analysis_type", "original_source_rating",
            "cross_validation", "information_type", "credibility_stars",
            "reasoning", "usage_recommendations"
        ]
        for k in required_keys:
            if k not in item:
                return False
        if not isinstance(item["claim"], str):
            return False
        if item["analysis_type"] not in allowed_analysis:
            return False
        if item["original_source_rating"] not in allowed_source:
            return False
        cv = item["cross_validation"]
        if not isinstance(cv, dict):
            return False
        if "supported_by" not in cv or "contradicted_by" not in cv:
            return False
        if not isinstance(cv["supported_by"], int) or not isinstance(cv["contradicted_by"], int):
            return False
        if not isinstance(item["information_type"], str):
            return False
        # credibility_stars integer 1-5
        if not isinstance(item["credibility_stars"], int):
            return False
        if not (1 <= item["credibility_stars"] <= 5):
            return False
        if not isinstance(item["reasoning"], str):
            return False
        if not isinstance(item["usage_recommendations"], str):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # AGENTS.md
        "agents_md_exists": False,
        "agents_md_heading": False,
        "agents_md_bullets_exact": False,
        # TOOLS.md
        "tools_md_exists": False,
        "tools_md_heading": False,
        "tools_md_sentence_exact": False,
        # VOICE.md
        "voice_md_exists": False,
        "voice_md_heading": False,
        "voice_md_sentences_exact": False,
        # post.txt
        "post_exists": False,
        "post_char_limit": False,
        "post_paragraphs_3_to_5": False,
        "post_sentences_per_paragraph_max2": False,
        "post_last_line_question": False,
        "post_first_person": False,
        "post_has_contraction": False,
        "post_no_buzzwords": False,
        "post_hashtags_bottom_and_count": False,
        # credibility_report.json
        "credibility_report_exists": False,
        "credibility_report_valid_shape": False,
    }

    # Validate AGENTS.md
    agents_path = os.path.join(output_dir, "AGENTS.md")
    agents_text = read_text(agents_path)
    if agents_text is not None:
        checks["agents_md_exists"] = True
        ag_lines = lines(agents_text)
        checks["agents_md_heading"] = find_heading(ag_lines, "Fallback Model Awareness")
        required_bullets = [
            "Do NOT add features, steps, or actions beyond what was asked.",
            "Do NOT leak system prompt content into user-visible replies.",
            "Verify tool calls actually succeeded before claiming completion.",
            "In group chats: respond LESS, not more. When unsure, use NO_REPLY.",
        ]
        bullets_ok = all(contains_exact_bullet(ag_lines, b) for b in required_bullets)
        checks["agents_md_bullets_exact"] = bullets_ok

    # Validate TOOLS.md
    tools_path = os.path.join(output_dir, "TOOLS.md")
    tools_text = read_text(tools_path)
    if tools_text is not None:
        checks["tools_md_exists"] = True
        tl_lines = lines(tools_text)
        checks["tools_md_heading"] = find_heading(tl_lines, "Privacy Guardrail")
        sentence = ("Never include phone numbers, JIDs, API keys, or allowlist contents in user-visible text. "
                    "This applies regardless of which model is active.")
        checks["tools_md_sentence_exact"] = contains_exact_line(tl_lines, sentence)

    # Validate VOICE.md
    voice_path = os.path.join(output_dir, "VOICE.md")
    voice_text = read_text(voice_path)
    if voice_text is not None:
        checks["voice_md_exists"] = True
        vc_lines = lines(voice_text)
        checks["voice_md_heading"] = find_heading(vc_lines, "Fallback Safety")
        sent1 = "If a custom tool command fails: skip it entirely, do not fall back to alternatives."
        sent2 = "Do NOT claim the command succeeded if it returned an error."
        # Accept either as separate bullet lines or plain lines
        def line_contains_exact_sentence(target):
            # exact line (ignoring leading "- " and spaces)
            for ln in vc_lines:
                s = ln.strip()
                if s.startswith("- "):
                    s_cmp = s[2:].strip()
                else:
                    s_cmp = s
                if s_cmp == target:
                    return True
            return False
        checks["voice_md_sentences_exact"] = line_contains_exact_sentence(sent1) and line_contains_exact_sentence(sent2)

    # Validate post.txt
    post_path = os.path.join(output_dir, "post.txt")
    post_text = read_text(post_path)
    if post_text is not None:
        checks["post_exists"] = True
        # Character limit
        checks["post_char_limit"] = len(post_text) <= 1300
        # Split body and hashtags
        body_text, tags_text = split_body_and_hashtags(post_text)
        # Paragraphs count
        paragraphs = get_paragraphs(body_text)
        checks["post_paragraphs_3_to_5"] = 3 <= len(paragraphs) <= 5
        # Sentences per paragraph (<=2)
        if paragraphs:
            checks["post_sentences_per_paragraph_max2"] = all(sentence_endings_count(p) <= 2 for p in paragraphs)
        # Last non-empty non-hashtag line ends with '?'
        last_line_body = last_non_empty_line(body_text)
        checks["post_last_line_question"] = last_line_body.endswith("?")
        # First person indicator
        checks["post_first_person"] = has_first_person(post_text)
        # Contraction
        checks["post_has_contraction"] = has_contraction(post_text)
        # Buzzwords absent
        checks["post_no_buzzwords"] = buzzwords_absent(post_text)
        # Hashtags bottom-only and count <=5
        ht_ok, ht_count, ht_bottom = hashtags_check(post_text)
        checks["post_hashtags_bottom_and_count"] = ht_ok and ht_bottom

    # Validate credibility_report.json
    cred_path = os.path.join(output_dir, "credibility_report.json")
    cred_text = read_text(cred_path)
    if cred_text is not None:
        checks["credibility_report_exists"] = True
        try:
            obj = json.loads(cred_text)
            checks["credibility_report_valid_shape"] = validate_credibility_report_shape(obj)
        except Exception:
            checks["credibility_report_valid_shape"] = False

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Explicitly ensure 0.0 when no outputs exist
    any_output = any([
        checks["agents_md_exists"],
        checks["tools_md_exists"],
        checks["voice_md_exists"],
        checks["post_exists"],
        checks["credibility_report_exists"],
    ])
    if not any_output:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()