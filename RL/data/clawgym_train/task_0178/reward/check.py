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

def count_words(text):
    if not text:
        return 0
    # Count tokens that look like words/numbers
    return len(re.findall(r"\b\w+\b", text))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "article_exists": False,
        "article_len_ok": False,
        "h2_order_ok": False,
        "opening_concrete_ok": False,
        "code_blocks_count_ok": False,
        "operators_note_present": False,
        "banned_phrases_absent": False,
        "takeaways_bullets_ok": False,
        "sources_exists": False,
        "sources_json_valid": False,
        "source_file_correct": False,
        "numbers_used_len_ok": False,
        "numbers_in_sources_in_article": False,
        "numbers_in_sources_in_input": False,
        "all_numeric_values_sourced": False,
    }

    article_path = os.path.join(output_dir, "article.md")
    sources_path = os.path.join(output_dir, "sources.json")
    research_path = os.path.join(input_dir, "research.json")

    article_text = None
    article_lines = []
    if os.path.isfile(article_path):
        checks["article_exists"] = True
        article_text = read_text(article_path)
        if article_text is None:
            article_text = ""
        article_lines = article_text.splitlines()

    # Load research text for cross-checking quantitative values
    research_text = read_text(research_path) or ""

    # Validate article
    if checks["article_exists"]:
        # length >= 800 words
        if count_words(article_text) >= 800:
            checks["article_len_ok"] = True

        # H2 headers order and exact match, and exactly these five
        expected_h2 = [
            "## The scene",
            "## Why drift hides",
            "## Implement the guardrails",
            "## Rollout plan",
            "## Takeaways",
        ]
        h2_lines = [ln.strip() for ln in article_lines if ln.strip().startswith("## ")]
        if h2_lines == expected_h2:
            checks["h2_order_ok"] = True

        # Opening concreteness: either first non-empty line is code fence, or first paragraph has a digit
        # Find first non-empty line
        first_idx = None
        for i, ln in enumerate(article_lines):
            if ln.strip() != "":
                first_idx = i
                break
        opening_ok = False
        if first_idx is not None:
            first_line = article_lines[first_idx].strip()
            if first_line.startswith("```"):
                opening_ok = True
            else:
                # First paragraph = lines until next blank
                para_lines = []
                for j in range(first_idx, len(article_lines)):
                    if article_lines[j].strip() == "":
                        break
                    para_lines.append(article_lines[j])
                para_text = "\n".join(para_lines)
                if re.search(r"\d", para_text) is not None:
                    opening_ok = True
        checks["opening_concrete_ok"] = opening_ok

        # At least two fenced code blocks: count lines starting with ```
        fence_lines = [ln for ln in article_lines if ln.strip().startswith("```")]
        if len(fence_lines) >= 4:
            checks["code_blocks_count_ok"] = True

        # Operator's note presence
        if "Operator's note:" in article_text:
            checks["operators_note_present"] = True

        # Banned phrases absent (case-insensitive)
        banned = [
            "In today's rapidly evolving landscape",
            "Moreover",
            "Furthermore",
            "game-changer",
            "cutting-edge",
            "revolutionary",
        ]
        lower_article = article_text.lower()
        banned_present = False
        for phrase in banned:
            if phrase.lower() in lower_article:
                banned_present = True
                break
        checks["banned_phrases_absent"] = (not banned_present)

        # Takeaways bullets: count '- ' lines under '## Takeaways' until next '## '
        takeaways_index = None
        for idx, ln in enumerate(article_lines):
            if ln.strip() == "## Takeaways":
                takeaways_index = idx
                break
        bullets_ok = False
        if takeaways_index is not None:
            bullet_count = 0
            for k in range(takeaways_index + 1, len(article_lines)):
                ln = article_lines[k]
                s = ln.strip()
                if s.startswith("## "):
                    break
                if s.startswith("- "):
                    bullet_count += 1
            if bullet_count >= 3:
                bullets_ok = True
        checks["takeaways_bullets_ok"] = bullets_ok

    # Validate sources.json
    sources_text = None
    sources = None
    if os.path.isfile(sources_path):
        checks["sources_exists"] = True
        sources_text = read_text(sources_path)
        if sources_text is None:
            sources_text = ""
        try:
            sources = json.loads(sources_text)
        except Exception:
            sources = None

        if isinstance(sources, dict) and "numbers_used" in sources and "source_file" in sources:
            checks["sources_json_valid"] = True
            if sources.get("source_file") == "input/research.json":
                checks["source_file_correct"] = True
            nums = sources.get("numbers_used")
            if isinstance(nums, list) and len(nums) >= 4 and all(isinstance(v, str) for v in nums):
                checks["numbers_used_len_ok"] = True

            # Check each numbers_used appears in article and in input research.json
            if checks["article_exists"]:
                in_article = True
                for v in nums if isinstance(nums, list) else []:
                    if v not in article_text:
                        in_article = False
                        break
                checks["numbers_in_sources_in_article"] = in_article
            else:
                checks["numbers_in_sources_in_article"] = False

            in_input = True
            for v in nums if isinstance(nums, list) else []:
                if v not in research_text:
                    in_input = False
                    break
            checks["numbers_in_sources_in_input"] = in_input
        else:
            checks["sources_json_valid"] = False

    # Check no unauthorized numbers in article (all quantitative values must be present in input/research.json)
    # Only run if article exists
    if checks["article_exists"]:
        quantitative_values = set()

        # All matches are captured as exact substrings for membership checking.
        # Percentages
        for m in re.finditer(r"\b\d+%", article_text):
            quantitative_values.add(m.group(0))

        # Times with units
        for m in re.finditer(r"\b\d+\s*(?:ms|s|sec|seconds|minutes|min|hrs|hours)\b", article_text, flags=re.IGNORECASE):
            quantitative_values.add(m.group(0))

        # Counts with 'of'
        for m in re.finditer(r"\b\d+\s+of\s+\d+\b", article_text, flags=re.IGNORECASE):
            quantitative_values.add(m.group(0))

        # Plain integers >= 10 not part of headings
        for ln in article_lines:
            if ln.lstrip().startswith("#"):
                # skip heading lines
                continue
            for m in re.finditer(r"\b\d+\b", ln):
                val = m.group(0)
                try:
                    ival = int(val)
                except Exception:
                    continue
                if ival >= 10:
                    quantitative_values.add(val)

        # Now ensure each quantitative value appears in research.json as substring
        all_sourced = True
        for val in quantitative_values:
            if val not in research_text:
                all_sourced = False
                break
        checks["all_numeric_values_sourced"] = all_sourced

    # Compute reward as fraction of passed checks
    # Ensure baseline: if both primary outputs are missing, reward = 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    # Baseline rule: if article and sources are both missing, reward stays 0.0
    if checks["article_exists"] or checks["sources_exists"]:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print exactly one JSON object
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()