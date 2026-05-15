import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def normalize_hyphens(text):
    # Replace common unicode dashes with ASCII hyphen for matching
    return text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-").replace("\u2010", "-").replace("\u2011", "-").replace("\u2027", "-").replace("\u2043", "-").replace("\uFE58", "-").replace("\uFE63", "-")

def count_checklist_items(text):
    count = 0
    for line in text.splitlines():
        # Accept "- [ ] ..." or "- [x] ...", case-insensitive for x
        if re.match(r"^\s*-\s*\[\s\]\s", line):
            count += 1
        elif re.match(r"^\s*-\s*\[\s*[xX]\s*\]\s", line):
            count += 1
    return count

def has_fenced_code_block(text):
    # Count lines starting with ```
    fence_lines = [ln for ln in text.splitlines() if ln.strip().startswith("```")]
    return len(fence_lines) >= 2

def has_failure_section(text):
    # Heading with "Failure" (case-insensitive) or phrase "what didn't work"
    lines = text.splitlines()
    for ln in lines:
        if ln.strip().startswith("#") and re.search(r"failure", ln, re.IGNORECASE):
            return True
    # Normalize apostrophes
    lower = text.lower().replace("didn’t", "didn't")
    if "what didn't work" in lower:
        return True
    return False

def article_banned_absent(text):
    # Case-insensitive banned phrases; normalize hyphens
    norm = normalize_hyphens(text)
    lower = norm.lower()
    banned = [
        "furthermore",
        "as we all know",
        "it's worth noting",
        "delve into",
        "ever-evolving landscape",
        "not only",
        "but also",
    ]
    for phrase in banned:
        if phrase in lower:
            return False
    return True

def has_table_header_round_score_decision(text):
    for ln in text.splitlines():
        if ln.strip().startswith("|") and ("Round" in ln and "Score" in ln and "Decision" in ln):
            # Ensure pipe-separated
            if re.search(r"\|.*Round.*\|.*Score.*\|.*Decision.*\|", ln):
                return True
    return False

def count_self_eval_rounds(text):
    # Count occurrences of "Self-Eval - Round" (case-insensitive)
    return len(re.findall(r"self[- ]eval\s*-\s*round", text, flags=re.IGNORECASE))

def get_final_self_eval_block(text):
    # Return substring from last "Self-Eval - Round" to end
    matches = list(re.finditer(r"self[- ]eval\s*-\s*round", text, flags=re.IGNORECASE))
    if not matches:
        return ""
    start = matches[-1].start()
    return text[start:]

def final_block_has_dimensions(block_text):
    needed = [
        "Information density",
        "Code/data ratio",
        "Failure showcase",
        "Conciseness",
        "Actionability",
        "Human feel",
    ]
    # Check each present (case-insensitive)
    low = block_text.lower()
    for name in needed:
        if name.lower() not in low:
            return False
    return True

def parse_composite_score(block_text):
    # Find line starting with "Composite:" and parse numeric score (may be "80/100" or "80")
    for ln in block_text.splitlines():
        if ln.strip().lower().startswith("composite:"):
            # Extract first number
            m = re.search(r"composite:\s*([0-9]+(?:\.[0-9]+)?)", ln, flags=re.IGNORECASE)
            if m:
                try:
                    val = float(m.group(1))
                    return val
                except Exception:
                    continue
            # Try form "XX/100"
            m2 = re.search(r"composite:\s*([0-9]+(?:\.[0-9]+)?)/\s*100", ln, flags=re.IGNORECASE)
            if m2:
                try:
                    val = float(m2.group(1))
                    return val
                except Exception:
                    continue
    return None

def final_block_has_keep(block_text):
    # Look for "Decision: KEEP" (case-insensitive)
    for ln in block_text.splitlines():
        if re.search(r"^\s*decision:\s*keep\b", ln, flags=re.IGNORECASE):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_research_facts": False,
        "has_article": False,
        "has_draft_log": False,
        "facts_has_min_checklist_items": False,
        "article_has_code_block": False,
        "article_has_failure_section": False,
        "article_refers_csv": False,
        "article_banned_phrases_absent": False,
        "draft_has_table_header": False,
        "draft_rounds_count_valid": False,
        "draft_final_block_has_all_dimensions": False,
        "draft_final_composite_ge_80": False,
        "draft_final_decision_keep": False,
    }

    # Paths
    facts_path = os.path.join(output_dir, "research_facts.md")
    article_path = os.path.join(output_dir, "article.md")
    draft_log_path = os.path.join(output_dir, "draft_log.md")

    # Existence checks
    if os.path.isfile(facts_path):
        checks["has_research_facts"] = True
        facts_text = read_text(facts_path)
        if count_checklist_items(facts_text) >= 5:
            checks["facts_has_min_checklist_items"] = True

    if os.path.isfile(article_path):
        checks["has_article"] = True
        article_text = read_text(article_path)
        if has_fenced_code_block(article_text):
            checks["article_has_code_block"] = True
        if has_failure_section(article_text):
            checks["article_has_failure_section"] = True
        if "mini_experiment.csv" in article_text:
            checks["article_refers_csv"] = True
        if article_banned_absent(article_text):
            checks["article_banned_phrases_absent"] = True

    if os.path.isfile(draft_log_path):
        checks["has_draft_log"] = True
        draft_text = read_text(draft_log_path)
        if has_table_header_round_score_decision(draft_text):
            checks["draft_has_table_header"] = True
        rounds_count = count_self_eval_rounds(draft_text)
        if 3 <= rounds_count <= 5:
            checks["draft_rounds_count_valid"] = True
        final_block = get_final_self_eval_block(draft_text)
        if final_block:
            if final_block_has_dimensions(final_block):
                checks["draft_final_block_has_all_dimensions"] = True
            composite = parse_composite_score(final_block)
            if composite is not None and composite >= 80.0:
                checks["draft_final_composite_ge_80"] = True
            if final_block_has_keep(final_block):
                checks["draft_final_decision_keep"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object on the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()