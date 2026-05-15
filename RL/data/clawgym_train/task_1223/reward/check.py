import json
import os
import sys
import csv
import re

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def get_primary_keyword(input_dir):
    p = os.path.join(input_dir, "target_keyword.txt")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None

def count_words(text):
    if not text:
        return 0
    # Remove simple markdown artifacts for word counting
    stripped = re.sub(r"[#>*_\-\[\]\(\)`]", " ", text)
    words = re.findall(r"\b\w+\b", stripped)
    return len(words)

def get_first_n_words(text, n):
    tokens = re.findall(r"\b\w+\b|\S", text)
    # Simpler: split on whitespace to match typical word counting for first 100 words
    tokens = re.findall(r"\S+", text)
    first = tokens[:n]
    return " ".join(first)

def parse_csv_rows(path):
    rows = []
    header = None
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for idx, row in enumerate(reader):
                if idx == 0:
                    header = row
                else:
                    rows.append(row)
    except Exception:
        return None, None
    return header, rows

def check_slug_constraints(slug, primary_kw):
    if not isinstance(slug, str) or not slug:
        return False
    parts = [p for p in slug.split("-") if p]
    if not (3 <= len(parts) <= 5):
        return False
    # token overlap with primary keyword tokens
    pk_tokens = [t for t in re.findall(r"[a-zA-Z0-9]+", primary_kw.lower()) if t]
    slug_tokens = [t.lower() for t in parts]
    overlap = set(pk_tokens).intersection(set(slug_tokens))
    return len(overlap) >= 1

def extract_h2_sections(article_text):
    lines = article_text.splitlines()
    h2s = []
    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            h2s.append(line[3:].strip())
    return h2s

def h1_is_first_and_contains_primary(article_text, primary_kw):
    lines = [ln for ln in article_text.splitlines() if ln.strip() != ""]
    if not lines:
        return False
    first = lines[0]
    if not first.startswith("# "):
        return False
    return primary_kw.lower() in first[2:].lower()

def count_keyword_occurrences(text, keyword):
    if not text or not keyword:
        return 0
    # Case-insensitive, non-overlapping occurrences of the phrase
    pattern = re.escape(keyword)
    return len(re.findall(pattern, text, flags=re.IGNORECASE))

def find_internal_links(md_text):
    # Markdown links with URL starting with "/"
    pattern = r"\[[^\]]+\]\((/[^)]+)\)"
    return re.findall(pattern, md_text)

def find_external_links(md_text):
    pattern = r"\[[^\]]+\]\(((?:http://|https://)[^)]+)\)"
    return re.findall(pattern, md_text)

def get_faq_q_count_after_section(md_text):
    lines = md_text.splitlines()
    faq_index = None
    for i, ln in enumerate(lines):
        if ln.strip() == "## FAQ":
            faq_index = i
            break
    if faq_index is None:
        return 0
    count = 0
    for j in range(faq_index + 1, len(lines)):
        ln = lines[j]
        if ln.startswith("## "):  # next H2 ends FAQ section
            break
        if ln.startswith("### "):
            count += 1
    return count

def get_h2_with_keyword_count(article_text, primary_kw):
    h2s = extract_h2_sections(article_text)
    cnt = 0
    for h in h2s:
        if primary_kw.lower() in h.lower():
            cnt += 1
    return cnt, len(h2s)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # File existence checks
    kr_path = os.path.join(output_dir, "keyword_research.csv")
    ca_path = os.path.join(output_dir, "competitor_analysis.md")
    brief_path = os.path.join(output_dir, "brief.md")
    article_path = os.path.join(output_dir, "article.md")
    meta_path = os.path.join(output_dir, "meta.json")
    schema_article_path = os.path.join(output_dir, "schema", "article.json")
    schema_faq_path = os.path.join(output_dir, "schema", "faq.json")
    scorecard_path = os.path.join(output_dir, "scorecard.json")

    checks["files_exist_keyword_research"] = os.path.isfile(kr_path)
    checks["files_exist_competitor_analysis"] = os.path.isfile(ca_path)
    checks["files_exist_brief"] = os.path.isfile(brief_path)
    checks["files_exist_article"] = os.path.isfile(article_path)
    checks["files_exist_meta"] = os.path.isfile(meta_path)
    checks["files_exist_schema_article"] = os.path.isfile(schema_article_path)
    checks["files_exist_schema_faq"] = os.path.isfile(schema_faq_path)
    checks["files_exist_scorecard"] = os.path.isfile(scorecard_path)

    primary_kw = get_primary_keyword(input_dir) or ""

    # Keyword research CSV validations
    checks["keyword_csv_header_correct"] = False
    checks["keyword_csv_min_rows"] = False
    checks["keyword_csv_first_row_is_primary"] = False
    checks["keyword_csv_scores_integer_range"] = False
    checks["keyword_csv_priority_score_valid"] = False

    if checks["files_exist_keyword_research"]:
        header, rows = parse_csv_rows(kr_path)
        expected_header = [
            "keyword",
            "intent",
            "relevance",
            "intent_match",
            "competition_gap",
            "business_value",
            "content_feasibility",
            "priority_score",
            "notes",
        ]
        if header == expected_header:
            checks["keyword_csv_header_correct"] = True
        if rows is not None and len(rows) >= 10:
            checks["keyword_csv_min_rows"] = True
        if rows and primary_kw:
            first_row_kw = (rows[0][0] if len(rows[0]) > 0 else "").strip()
            if first_row_kw.lower() == primary_kw.strip().lower():
                checks["keyword_csv_first_row_is_primary"] = True

        # Validate score integers and priority sum
        if rows:
            all_integers_in_range = True
            all_priority_valid = True
            for r in rows:
                if len(r) < 9:
                    all_integers_in_range = False
                    all_priority_valid = False
                    break
                try:
                    rel = int(r[2].strip())
                    im = int(r[3].strip())
                    cg = int(r[4].strip())
                    bv = int(r[5].strip())
                    cf = int(r[6].strip())
                    ps = int(r[7].strip())
                    for v in [rel, im, cg, bv, cf]:
                        if v < 1 or v > 5:
                            all_integers_in_range = False
                    if ps != (rel + im + cg + bv + cf):
                        all_priority_valid = False
                except Exception:
                    all_integers_in_range = False
                    all_priority_valid = False
                    break
            if all_integers_in_range:
                checks["keyword_csv_scores_integer_range"] = True
            if all_priority_valid:
                checks["keyword_csv_priority_score_valid"] = True

    # Competitor analysis validations
    checks["competitor_has_top5_section"] = False
    checks["competitor_top5_numbered_list_1_to_5"] = False
    checks["competitor_has_table_stakes_section"] = False
    checks["competitor_has_content_gaps_section"] = False
    checks["competitor_has_opportunity_rating_section"] = False

    if checks["files_exist_competitor_analysis"]:
        ca_text = read_file(ca_path) or ""
        if "Top 5 Results" in ca_text:
            checks["competitor_has_top5_section"] = True
        numbered_present = all(re.search(rf"^{i}\.\s", ca_text, flags=re.MULTILINE) for i in range(1, 6))
        if numbered_present:
            checks["competitor_top5_numbered_list_1_to_5"] = True
        if "Table-Stakes Subtopics" in ca_text:
            checks["competitor_has_table_stakes_section"] = True
        if "Content Gaps" in ca_text:
            checks["competitor_has_content_gaps_section"] = True
        if "Opportunity Rating" in ca_text:
            checks["competitor_has_opportunity_rating_section"] = True

    # Brief validations
    checks["brief_starts_with_content_brief"] = False
    checks["brief_has_required_fields_lines"] = False
    checks["brief_has_audience_section"] = False
    checks["brief_has_must_cover_with_3_items"] = False
    checks["brief_has_differentiation_with_2_items"] = False
    checks["brief_has_internal_links_with_to_and_from"] = False
    checks["brief_has_cta_section"] = False

    if checks["files_exist_brief"]:
        btext = read_file(brief_path) or ""
        blines = btext.splitlines()
        if blines and blines[0].startswith("# Content Brief:"):
            checks["brief_starts_with_content_brief"] = True
        required_line_starts = ["Target keyword:", "Secondary keywords:", "Search intent:", "Target word count:", "Content type:"]
        has_required = all(any(ln.startswith(r) for ln in blines) for r in required_line_starts)
        if has_required:
            checks["brief_has_required_fields_lines"] = True
        if re.search(r"^##\s+Audience\b", btext, flags=re.MULTILINE):
            checks["brief_has_audience_section"] = True
        # Count list items under Must-Cover
        must_cover_items = 0
        if re.search(r"^##\s+Must-Cover Subtopics\b", btext, flags=re.MULTILINE):
            # Simple count of lines starting with a number or dash after the section until next ##
            lines = blines
            start = None
            for i, ln in enumerate(lines):
                if re.match(r"^##\s+Must-Cover Subtopics\b", ln):
                    start = i + 1
                    break
            if start is not None:
                for j in range(start, len(lines)):
                    if lines[j].startswith("## "):
                        break
                    if re.match(r"^\s*(?:\d+\.\s+|-|\*)\s*\S", lines[j]):
                        must_cover_items += 1
        if must_cover_items >= 3:
            checks["brief_has_must_cover_with_3_items"] = True

        # Differentiation Angles
        diff_items = 0
        if re.search(r"^##\s+Differentiation Angles\b", btext, flags=re.MULTILINE):
            lines = blines
            start = None
            for i, ln in enumerate(lines):
                if re.match(r"^##\s+Differentiation Angles\b", ln):
                    start = i + 1
                    break
            if start is not None:
                for j in range(start, len(lines)):
                    if lines[j].startswith("## "):
                        break
                    if re.match(r"^\s*(?:\d+\.\s+|-|\*)\s*\S", lines[j]):
                        diff_items += 1
        if diff_items >= 2:
            checks["brief_has_differentiation_with_2_items"] = True

        # Internal Links section with Link TO and Link FROM
        has_internal_links_section = re.search(r"^##\s+Internal Links\b", btext, flags=re.MULTILINE) is not None
        has_link_to = re.search(r"^\s*-\s*Link TO:", btext, flags=re.MULTILINE) is not None
        has_link_from = re.search(r"^\s*-\s*Link FROM:", btext, flags=re.MULTILINE) is not None
        if has_internal_links_section and has_link_to and has_link_from:
            checks["brief_has_internal_links_with_to_and_from"] = True

        if re.search(r"^##\s+CTA\b", btext, flags=re.MULTILINE):
            checks["brief_has_cta_section"] = True

    # Meta validations
    checks["meta_valid_json"] = False
    checks["meta_title_constraints"] = False
    checks["meta_description_constraints"] = False
    checks["meta_slug_constraints"] = False
    checks["meta_contains_primary_in_title_and_description"] = False

    meta = None
    if checks["files_exist_meta"]:
        meta = load_json(meta_path)
        if meta is not None and isinstance(meta, dict):
            checks["meta_valid_json"] = True
            title = meta.get("title", "")
            md = meta.get("meta_description", "")
            slug = meta.get("url_slug", "")
            if isinstance(title, str) and len(title) < 60:
                checks["meta_title_constraints"] = True
            if isinstance(md, str) and 150 <= len(md) <= 160:
                checks["meta_description_constraints"] = True
            if primary_kw:
                contains_title = isinstance(title, str) and (primary_kw.lower() in title.lower())
                contains_md = isinstance(md, str) and (primary_kw.lower() in md.lower())
                if contains_title and contains_md:
                    checks["meta_contains_primary_in_title_and_description"] = True
            if isinstance(slug, str) and primary_kw:
                if check_slug_constraints(slug, primary_kw):
                    checks["meta_slug_constraints"] = True

    # Article validations
    checks["article_h1_has_primary_and_is_first"] = False
    checks["article_h2_count_between_5_and_8"] = False
    checks["article_h2_primary_count_between_1_and_3"] = False
    checks["article_has_faq_section_with_5_to_7_questions"] = False
    checks["article_has_conclusion_cta_section"] = False
    checks["article_word_count_at_least_1200"] = False
    checks["article_primary_in_first_100_words"] = False
    checks["article_internal_links_at_least_3"] = False
    checks["article_external_links_at_least_2"] = False
    checks["article_primary_total_occurrences_between_4_and_12"] = False

    article_text = None
    if checks["files_exist_article"]:
        article_text = read_file(article_path) or ""
        if primary_kw and h1_is_first_and_contains_primary(article_text, primary_kw):
            checks["article_h1_has_primary_and_is_first"] = True

        hk_count, h2_total = get_h2_with_keyword_count(article_text, primary_kw if primary_kw else "")
        if 5 <= h2_total <= 8:
            checks["article_h2_count_between_5_and_8"] = True
        if primary_kw and 1 <= hk_count <= 3:
            checks["article_h2_primary_count_between_1_and_3"] = True

        faq_q_count = get_faq_q_count_after_section(article_text)
        if faq_q_count >= 5 and faq_q_count <= 7:
            checks["article_has_faq_section_with_5_to_7_questions"] = True

        if re.search(r"^##\s+Conclusion \+ CTA$", article_text, flags=re.MULTILINE):
            checks["article_has_conclusion_cta_section"] = True

        wc = count_words(article_text)
        if wc >= 1200:
            checks["article_word_count_at_least_1200"] = True

        if primary_kw:
            first_100 = get_first_n_words(article_text, 100)
            if primary_kw.lower() in first_100.lower():
                checks["article_primary_in_first_100_words"] = True

        internal_links = find_internal_links(article_text)
        if len(internal_links) >= 3:
            checks["article_internal_links_at_least_3"] = True

        external_links = find_external_links(article_text)
        if len(external_links) >= 2:
            checks["article_external_links_at_least_2"] = True

        if primary_kw:
            total_occ = count_keyword_occurrences(article_text, primary_kw)
            if 4 <= total_occ <= 12:
                checks["article_primary_total_occurrences_between_4_and_12"] = True

    # Schema validations
    checks["schema_article_valid_and_matches_meta"] = False
    checks["schema_faq_valid_structure"] = False

    if checks["files_exist_schema_article"]:
        sa = load_json(schema_article_path)
        if sa and isinstance(sa, dict) and meta and checks["meta_valid_json"]:
            ctx_ok = "@context" in sa
            type_ok = sa.get("@type") == "Article"
            headline_ok = sa.get("headline") == meta.get("title")
            desc_ok = sa.get("description") == meta.get("meta_description")
            if ctx_ok and type_ok and headline_ok and desc_ok:
                checks["schema_article_valid_and_matches_meta"] = True

    if checks["files_exist_schema_faq"]:
        sf = load_json(schema_faq_path)
        if sf and isinstance(sf, dict):
            ctx_ok = "@context" in sf
            type_ok = sf.get("@type") == "FAQPage"
            me = sf.get("mainEntity")
            valid_items = False
            if isinstance(me, list) and 5 <= len(me) <= 7:
                items_ok = True
                for item in me:
                    if not isinstance(item, dict):
                        items_ok = False
                        break
                    if item.get("@type") != "Question":
                        items_ok = False
                        break
                    aa = item.get("acceptedAnswer")
                    if not isinstance(aa, dict):
                        items_ok = False
                        break
                    if aa.get("@type") != "Answer":
                        items_ok = False
                        break
                    if "text" not in aa or not isinstance(aa["text"], str) or aa["text"] == "":
                        items_ok = False
                        break
                valid_items = items_ok
            if ctx_ok and type_ok and valid_items:
                checks["schema_faq_valid_structure"] = True

    # Scorecard validations
    checks["scorecard_valid_and_totals_100"] = False
    if checks["files_exist_scorecard"]:
        sc = load_json(scorecard_path)
        required_keys = [
            "keyword_optimization",
            "content_depth",
            "readability",
            "practical_value",
            "structure",
            "internal_links",
            "external_links",
            "media",
            "meta_tags",
            "cta",
            "total",
        ]
        if sc and isinstance(sc, dict) and all(k in sc for k in required_keys):
            try:
                vals = [int(sc[k]) for k in required_keys]
                # Ensure they are integers in JSON (converted OK)
                crit_sum = sum(int(sc[k]) for k in required_keys if k != "total")
                total = int(sc["total"])
                if crit_sum == total == 100:
                    checks["scorecard_valid_and_totals_100"] = True
            except Exception:
                checks["scorecard_valid_and_totals_100"] = False

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Baseline: if output directory missing or empty of required artifacts, ensure 0.0
    required_exist = [
        checks["files_exist_keyword_research"],
        checks["files_exist_competitor_analysis"],
        checks["files_exist_brief"],
        checks["files_exist_article"],
        checks["files_exist_meta"],
        checks["files_exist_schema_article"],
        checks["files_exist_schema_faq"],
        checks["files_exist_scorecard"],
    ]
    if not any(required_exist):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()