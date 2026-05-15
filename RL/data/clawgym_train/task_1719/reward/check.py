import json
import os
import re
import sys
import csv

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def get_primary_and_secondary_keywords(keywords_path):
    data = load_json(keywords_path)
    primary = None
    secondary = []
    if isinstance(data, dict):
        # Try common keys
        for k in ["primary", "primary_keyword", "primaryKeyword"]:
            if k in data and isinstance(data[k], str):
                primary = data[k]
                break
        for k in ["secondary", "secondary_keywords", "secondaryKeywords"]:
            if k in data and isinstance(data[k], list):
                secondary = [s for s in data[k] if isinstance(s, str)]
                break
    return primary, secondary

def parse_sources_catalog(sources_md_text):
    # Extract entries of pattern: [ID] Title — Type
    # This will scan entire text; supports bullets or tables as long as pattern appears
    pattern = re.compile(r"\[\s*([^\]\n]+)\s*\]\s+(.*?)\s+—\s+(Primary|Expert|Secondary)\b", re.UNICODE)
    catalog = {}
    for m in pattern.finditer(sources_md_text):
        _id = m.group(1).strip()
        title = m.group(2).strip()
        _type = m.group(3).strip()
        # If multiple entries share ID, last one wins (unlikely)
        catalog[_id] = {"title": title, "type": _type}
    return catalog

def extract_sources_from_article(article_text):
    # Find the last "Sources" section (header may be with or without '#')
    lines = [ln.rstrip("\n") for ln in article_text.splitlines()]
    sources_header_idx = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        # normalize by removing leading hashes and spaces
        normalized = stripped.lstrip("#").strip().lower()
        if normalized == "sources":
            sources_header_idx = idx
    if sources_header_idx is None:
        return None, False, [], False  # no sources section
    # Collect source lines following the header until EOF or until a non-source non-empty line
    src_lines = []
    after_lines = lines[sources_header_idx + 1 :]
    pattern_line = re.compile(r"^\-\s+\[([^\]]+)\]\s+(.*?)\s+—\s+(Primary|Expert|Secondary)\s*$")
    end_clean = True
    for i, l in enumerate(after_lines):
        if not l.strip():
            # allow blank lines, but if we already started collecting and then see blank line,
            # continue to see if only blanks remain
            continue
        if pattern_line.match(l):
            src_lines.append(l.strip())
        else:
            # Non-source content after the Sources header; not clean end
            end_clean = False
            break
    # Check that after the last collected source line, there is nothing but whitespace to the end
    if end_clean:
        # verify that any remaining lines are blank
        remainder = after_lines[len([ln for ln in after_lines if pattern_line.match(ln) or not ln.strip()]):]
        # But above approach is tricky; better simply check from the point we broke
        pass
    # For a robust check, recompute: find the index of the last matched line in after_lines
    last_match_idx = -1
    for i, l in enumerate(after_lines):
        if pattern_line.match(l):
            last_match_idx = i
        elif l.strip() and last_match_idx != -1:
            # a non-blank, non-source after sources began
            end_clean = False
            break
    # If we had no sources, it's still a sources section but invalid
    return sources_header_idx, end_clean, src_lines, True

def parse_sources_lines(src_lines):
    # Parse "- [ID] Title — Type"
    entries = []
    pattern_line = re.compile(r"^\-\s+\[([^\]]+)\]\s+(.*?)\s+—\s+(Primary|Expert|Secondary)\s*$")
    for l in src_lines:
        m = pattern_line.match(l)
        if not m:
            return None
        _id = m.group(1).strip()
        title = m.group(2).strip()
        _type = m.group(3).strip()
        entries.append({"id": _id, "title": title, "type": _type})
    return entries

def count_primary_keyword_occurrences(text, primary_keyword):
    if not primary_keyword:
        return 0
    # Case-insensitive whole phrase with word boundaries around beginning and end
    # For multi-word phrases, \b works well for non-alphanumeric on edges
    pattern = re.compile(r"\b" + re.escape(primary_keyword) + r"\b", re.IGNORECASE)
    return len(pattern.findall(text))

def get_first_nonempty_line(lines):
    for ln in lines:
        if ln.strip():
            return ln
    return ""

def check_first_sentence_question_hook(line):
    # Remove Markdown header markers if present
    s = line.strip()
    s = s.lstrip("#").strip()
    if not s:
        return False
    # Must end with '?'
    if not s.endswith("?"):
        return False
    # Count words (split on whitespace)
    words = re.findall(r"\b\w[\w\-']*\b", s)
    return len(words) <= 25

def count_headings(lines):
    h2 = 0
    h3 = 0
    for ln in lines:
        if ln.startswith("### "):
            h3 += 1
        elif ln.startswith("## "):
            # Count only those that are not H3
            h2 += 1
    return h2, h3

def count_quotes_with_attribution(text):
    # Count occurrences of: "Statement," said Name, Title/Organization.
    # ASCII quotes only, ensure a comma before closing quote, then ' said ', then Name (non-comma), comma, space, Title/Org.
    pattern = re.compile(r"\"[^\"\n]*?,\" said [^,\n]+, [^\n\"\r]+")
    matches = pattern.findall(text)
    return len(matches)

def load_stat_phrases(stats_csv_path):
    phrases = []
    try:
        with open(stats_csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return phrases
            # Assume header present; collect all non-empty cells from subsequent rows
            for row in rows[1:]:
                for cell in row:
                    cell_val = (cell or "").strip()
                    # collect reasonably long phrases (>= 3 characters) to avoid trivial matches
                    if len(cell_val) >= 3:
                        phrases.append(cell_val)
    except Exception:
        pass
    return phrases

def article_paragraphs_with_sentence_limits(text, max_sentences=5):
    # Split paragraphs on blank lines
    paragraphs = []
    current = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                paragraphs.append("\n".join(current).strip())
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current).strip())
    # For each paragraph, count sentence terminators ., ?, !
    ok = True
    for p in paragraphs:
        # remove code blocks content ticks to reduce false counts
        # but keep simple: count ., ?, !
        count = p.count(".") + p.count("?") + p.count("!")
        if count > max_sentences:
            ok = False
            break
    return ok

def word_count(text):
    words = re.findall(r"\b\w[\w\-']*\b", text)
    return len(words)

def build_checks(workspace_root):
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "has_article_file": False,
        "has_seo_file": False,
        "has_citations_file": False,
        "h1_first_line_contains_primary": False,
        "first_sentence_question_hook": False,
        "at_least_three_h2": False,
        "at_least_one_h3": False,
        "at_least_two_quotes": False,
        "includes_stat_phrase": False,
        "primary_keyword_count_in_range": False,
        "includes_shadow_it": False,
        "paragraphs_sentence_limit_ok": False,
        "word_count_min_700": False,
        "sources_section_formatted": False,
        "sources_count_and_types_ok": False,
        "sources_exist_in_catalog": False,
        "sources_section_at_end": False,
        "citations_match_sources": False,
        "seo_title_length_ok": False,
        "seo_description_length_ok": False,
        "seo_keywords_valid": False,
        "cross_h1_contains_primary": False
    }

    # Paths
    keywords_path = os.path.join(input_dir, "keywords.json")
    sources_md_path = os.path.join(input_dir, "sources.md")
    stats_csv_path = os.path.join(input_dir, "stats.csv")
    brief_json_path = os.path.join(input_dir, "brief.json")  # not used for scoring

    article_path = os.path.join(output_dir, "article.md")
    seo_path = os.path.join(output_dir, "seo.json")
    citations_path = os.path.join(output_dir, "citations.json")

    # Load inputs
    primary_keyword, secondary_keywords = get_primary_and_secondary_keywords(keywords_path)
    sources_md_text = read_text(sources_md_path) or ""
    stats_phrases = load_stat_phrases(stats_csv_path)

    sources_catalog = parse_sources_catalog(sources_md_text)

    # Output existence checks
    article_text = read_text(article_path)
    if article_text is not None:
        checks["has_article_file"] = True
    seo_json = load_json(seo_path)
    if seo_json is not None:
        checks["has_seo_file"] = True
    citations_json = load_json(citations_path)
    if citations_json is not None:
        checks["has_citations_file"] = True

    # Article checks
    sources_in_article = []
    if checks["has_article_file"]:
        lines = [ln.rstrip("\n") for ln in article_text.splitlines()]
        # H1 as first non-empty line
        first_line = get_first_nonempty_line(lines)
        if first_line.startswith("# "):
            # must contain primary keyword exactly as in keywords.json
            if primary_keyword and primary_keyword in first_line:
                checks["h1_first_line_contains_primary"] = True
                checks["cross_h1_contains_primary"] = True
        # First sentence question hook (we assume first sentence is the H1 line content)
        if first_line.strip():
            if check_first_sentence_question_hook(first_line):
                checks["first_sentence_question_hook"] = True
        # Headings
        h2_count, h3_count = count_headings(lines)
        if h2_count >= 3:
            checks["at_least_three_h2"] = True
        if h3_count >= 1:
            checks["at_least_one_h3"] = True
        # Quotes with attribution
        if count_quotes_with_attribution(article_text) >= 2:
            checks["at_least_two_quotes"] = True
        # Stats phrase inclusion (verbatim)
        if stats_phrases:
            includes_stat = any(phrase in article_text for phrase in stats_phrases)
            if includes_stat:
                checks["includes_stat_phrase"] = True
        # Primary keyword usage 6–20 times (case-insensitive)
        if primary_keyword:
            count_pk = count_primary_keyword_occurrences(article_text, primary_keyword)
            if 6 <= count_pk <= 20:
                checks["primary_keyword_count_in_range"] = True
        # shadow IT phrase at least once (case-insensitive)
        if re.search(r"\bshadow IT\b", article_text, re.IGNORECASE):
            checks["includes_shadow_it"] = True
        # Paragraph sentence limits
        if article_paragraphs_with_sentence_limits(article_text, max_sentences=5):
            checks["paragraphs_sentence_limit_ok"] = True
        # Word count minimum
        if word_count(article_text) >= 700:
            checks["word_count_min_700"] = True
        # Sources section parsing
        hdr_idx, end_clean, src_lines, has_sources_section = extract_sources_from_article(article_text)
        if has_sources_section and src_lines:
            parsed_entries = parse_sources_lines(src_lines)
            if parsed_entries is not None:
                sources_in_article = parsed_entries
                # formatted: all lines match; count exactly five
                if len(parsed_entries) == 5:
                    checks["sources_section_formatted"] = True
                # types check: exactly 3 Primary, 1 Expert, 1 Secondary
                type_counts = {"Primary": 0, "Expert": 0, "Secondary": 0}
                for e in parsed_entries:
                    if e["type"] in type_counts:
                        type_counts[e["type"]] += 1
                if type_counts["Primary"] == 3 and type_counts["Expert"] == 1 and type_counts["Secondary"] == 1:
                    checks["sources_count_and_types_ok"] = True
                # exist in catalog (IDs present and type matches; title optional)
                exist_ok = True
                for e in parsed_entries:
                    sid = e["id"]
                    if sid not in sources_catalog:
                        exist_ok = False
                        break
                    if sources_catalog[sid]["type"] != e["type"]:
                        exist_ok = False
                        break
                if exist_ok:
                    checks["sources_exist_in_catalog"] = True
                # section at end (no non-whitespace, non-source content after)
                # Validate that after the last parsed source line, only blanks remain
                if hdr_idx is not None:
                    # Build a set of indices of source lines relative to the article
                    # We will iterate after the header to find continuous block of sources and blanks
                    after_lines = [ln for ln in lines[hdr_idx+1:]]
                    pattern_line = re.compile(r"^\-\s+\[([^\]]+)\]\s+(.*?)\s+—\s+(Primary|Expert|Secondary)\s*$")
                    saw_source = False
                    tail_clean = True
                    for l in after_lines:
                        if not l.strip():
                            # blank lines okay
                            continue
                        if pattern_line.match(l):
                            saw_source = True
                            continue
                        else:
                            # Any other non-blank content after Sources header invalidates end
                            tail_clean = False
                            break
                    if tail_clean and saw_source:
                        checks["sources_section_at_end"] = True

    # Citations JSON checks
    if checks["has_citations_file"]:
        cj = citations_json
        valid_citations_json = isinstance(cj, dict) and isinstance(cj.get("sources"), list)
        if valid_citations_json:
            cj_list = cj["sources"]
            # Each item must have id, type, title
            items_ok = True
            for it in cj_list:
                if not isinstance(it, dict):
                    items_ok = False
                    break
                if not all(k in it for k in ["id", "type", "title"]):
                    items_ok = False
                    break
                if not isinstance(it["id"], str) or not isinstance(it["type"], str) or not isinstance(it["title"], str):
                    items_ok = False
                    break
            # Must be 5 and match the set from article's Sources section
            if items_ok and len(cj_list) == 5 and sources_in_article:
                set_article = {(e["id"], e["title"], e["type"]) for e in sources_in_article}
                set_citations = {(e["id"], e["title"], e["type"]) for e in cj_list}
                if set_article == set_citations:
                    checks["citations_match_sources"] = True

    # SEO JSON checks
    if checks["has_seo_file"]:
        sj = seo_json
        if isinstance(sj, dict):
            title = sj.get("title")
            desc = sj.get("description")
            kw = sj.get("keywords")
            if isinstance(title, str):
                l = len(title)
                if 50 <= l <= 60:
                    checks["seo_title_length_ok"] = True
            if isinstance(desc, str):
                l = len(desc)
                if 150 <= l <= 160:
                    checks["seo_description_length_ok"] = True
            # keywords array contains primary and at least three secondary
            if isinstance(kw, list):
                kw_strs = [k for k in kw if isinstance(k, str)]
                has_primary = primary_keyword in kw_strs if primary_keyword else False
                secondary_set = set(secondary_keywords)
                sec_included = sum(1 for k in kw_strs if k in secondary_set)
                if has_primary and sec_included >= 3:
                    checks["seo_keywords_valid"] = True

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    checks = build_checks(workspace_root)
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if no output files exist, reward must be 0.0
    if not (checks.get("has_article_file") or checks.get("has_seo_file") or checks.get("has_citations_file")):
        reward = 0.0
    else:
        # reward is proportion of checks passed
        reward = passed / total if total > 0 else 0.0
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()