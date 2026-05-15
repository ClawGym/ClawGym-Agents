import json
import os
import re
import sys

def load_research_map(research_path):
    research_map = {}
    if not os.path.isfile(research_path):
        return research_map
    try:
        with open(research_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    _id = obj.get("id")
                    _type = obj.get("type")
                    if isinstance(_id, str) and isinstance(_type, str):
                        research_map[_id] = _type
                except Exception:
                    continue
    except Exception:
        return {}
    return research_map

def parse_citation_ids(text):
    # [cite:ID] where ID is any sequence of non-] and non-whitespace
    ids = re.findall(r"\[cite:([^\]\s]+)\]", text)
    return set(ids)

def compute_word_count(text):
    # Step 1: remove [cite:ID] tags
    text = re.sub(r"\[cite:[^\]\s]+\]", "", text)
    # Step 2: strip heading markers (#... )
    lines = text.splitlines()
    cleaned_lines = []
    for ln in lines:
        cleaned_lines.append(re.sub(r"^\s*#+\s+", "", ln))
    cleaned = "\n".join(cleaned_lines)
    # Step 3: split on whitespace and count tokens with at least one alphanumeric
    tokens = re.split(r"\s+", cleaned.strip())
    count = 0
    for t in tokens:
        if re.search(r"[A-Za-z0-9]", t):
            count += 1
    return count

def paragraphs(text):
    # Paragraphs are blocks separated by one or more blank lines
    parts = re.split(r"\n\s*\n", text.strip())
    # Filter out empty strings if any
    return [p for p in parts if p.strip() != ""]

def headings_in_order(text, required_headings):
    # Ensure each required heading appears in sequence; extra headings allowed
    # Match lines like "## Problem" exactly (allow trailing spaces)
    last_pos = -1
    for h in required_headings:
        # Find the first match after last_pos
        pattern = r"^" + re.escape("## " + h) + r"\s*$"
        found = False
        for m in re.finditer(pattern, text, flags=re.MULTILINE):
            if m.start() > last_pos:
                last_pos = m.start()
                found = True
                break
        if not found:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    article_path = os.path.join(output_dir, "article.md")
    metadata_path = os.path.join(output_dir, "metadata.json")
    research_path = os.path.join(input_dir, "research.jsonl")

    checks = {
        "has_article": False,
        "has_metadata": False,
        "headings_order": False,
        "thesis_in_first_two_paragraphs": False,
        "percentage_present": False,
        "analogy_paragraph_present": False,
        "citations_exist_in_research": False,
        "citations_requirements_met": False,
        "metadata_fields_valid": False,
        "metadata_citations_match": False,
        "keywords_appear_in_article": False,
        "word_count_matches_and_range": False,
    }

    article_text = ""
    metadata = None
    research_map = load_research_map(research_path)
    cited_ids = set()
    required_headings = [
        "Problem",
        "Root Cause Analysis",
        "Solution",
        "Evidence of Effectiveness",
        "Implementation Guidance",
        "Conclusion",
    ]

    if os.path.isfile(article_path):
        try:
            with open(article_path, "r", encoding="utf-8") as f:
                article_text = f.read()
            checks["has_article"] = True
        except Exception:
            article_text = ""
            checks["has_article"] = False

    if checks["has_article"]:
        # Headings order
        if headings_in_order(article_text, required_headings):
            checks["headings_order"] = True

        # Thesis in first two paragraphs: any line beginning with "Thesis:"
        paras = paragraphs(article_text)
        first_two = paras[:2]
        thesis_found = False
        for p in first_two:
            for line in p.splitlines():
                if line.strip().startswith("Thesis:"):
                    thesis_found = True
                    break
            if thesis_found:
                break
        checks["thesis_in_first_two_paragraphs"] = thesis_found

        # Percentage presence
        if re.search(r"\b\d{1,3}%\b", article_text):
            checks["percentage_present"] = True

        # Analogy paragraph present: a paragraph whose first token is exactly "Analogy:"
        analogy_ok = False
        for p in paras:
            stripped = p.lstrip()
            if not stripped:
                continue
            first_token = stripped.split(None, 1)[0] if stripped.split() else ""
            if first_token == "Analogy:":
                analogy_ok = True
                break
        checks["analogy_paragraph_present"] = analogy_ok

        # Citations in article
        cited_ids = parse_citation_ids(article_text)

        # Citations exist in research (avoid vacuous pass)
        if cited_ids:
            all_exist = all(cid in research_map for cid in cited_ids)
            checks["citations_exist_in_research"] = all_exist
        else:
            checks["citations_exist_in_research"] = False

        # Citations requirements: at least 3 unique, include at least one stat-type and one expert_quote
        if checks["citations_exist_in_research"]:
            types = [research_map[cid] for cid in cited_ids if cid in research_map]
            types_lower = [t.lower() for t in types]
            has_stat = any((t == "stat" or t.startswith("stat")) for t in types_lower)
            has_expert = any(t == "expert_quote" for t in types_lower)
            if len(cited_ids) >= 3 and has_stat and has_expert:
                checks["citations_requirements_met"] = True

    # Metadata checks
    if os.path.isfile(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            checks["has_metadata"] = True
        except Exception:
            metadata = None
            checks["has_metadata"] = False

    if checks["has_metadata"]:
        # Validate fields
        fields_ok = True
        thesis_str = metadata.get("thesis")
        keywords = metadata.get("keywords")
        citations_meta = metadata.get("citations")
        word_count_meta = metadata.get("word_count")

        if not (isinstance(thesis_str, str) and thesis_str.strip()):
            fields_ok = False
        if not (isinstance(keywords, list) and 5 <= len(keywords) <= 10 and all(isinstance(k, str) for k in keywords)):
            fields_ok = False
        if not (isinstance(citations_meta, list) and all(isinstance(c, dict) for c in citations_meta)):
            fields_ok = False
        else:
            for c in citations_meta:
                if not (isinstance(c.get("id"), str) and isinstance(c.get("type"), str)):
                    fields_ok = False
                    break
        if not isinstance(word_count_meta, int):
            fields_ok = False

        checks["metadata_fields_valid"] = fields_ok

        # metadata_citations_match: exact set and correct types vs research
        meta_ids = set()
        meta_types_ok = True
        if citations_meta and isinstance(citations_meta, list):
            for c in citations_meta:
                cid = c.get("id")
                ctype = c.get("type")
                if isinstance(cid, str):
                    meta_ids.add(cid)
                # Check type against research map when possible
                if not (isinstance(cid, str) and isinstance(ctype, str) and cid in research_map and ctype == research_map[cid]):
                    meta_types_ok = False
        # Avoid vacuous pass: require both sets non-empty
        if cited_ids and meta_ids and (meta_ids == cited_ids) and meta_types_ok:
            checks["metadata_citations_match"] = True

        # keywords appear in article: at least 3 appear (case-insensitive substring)
        if checks["has_article"] and isinstance(keywords, list):
            found_count = 0
            lower_article = article_text.lower()
            for k in keywords:
                if isinstance(k, str) and k.strip():
                    if k.lower() in lower_article:
                        found_count += 1
            if found_count >= 3:
                checks["keywords_appear_in_article"] = True

        # word count check
        if checks["has_article"] and isinstance(word_count_meta, int):
            wc = compute_word_count(article_text)
            if 1000 <= wc <= 1400 and wc == word_count_meta:
                checks["word_count_matches_and_range"] = True

    # Compute reward as proportion of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output is empty/missing required artifacts, reward must be 0.0
    # If neither article nor metadata exists, set reward to 0.0 explicitly
    if not checks["has_article"] and not checks["has_metadata"]:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()