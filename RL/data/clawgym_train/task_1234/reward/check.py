import json
import os
import sys
import re
import csv

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    txt = read_text(path)
    if txt is None:
        return None
    # Normalize newlines
    return txt.splitlines()

def find_first_nonempty_line(lines):
    for idx, line in enumerate(lines):
        if line.strip() != "":
            return idx, line
    return None, None

def count_bullet_lines(lines, prefix="- "):
    return sum(1 for ln in lines if ln.strip().startswith(prefix))

def section_indices(lines, labels):
    """
    Return a dict mapping label to (start_index, end_index) where end_index is exclusive.
    Lines are matched by exact stripped equality to the label.
    """
    positions = {}
    inds = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s in labels:
            inds.append((s, i))
    inds.sort(key=lambda x: x[1])
    for idx, (label, start) in enumerate(inds):
        end = len(lines)
        if idx + 1 < len(inds):
            end = inds[idx + 1][1]
        positions[label] = (start + 1, end)  # content starts after the label line
    return positions

def get_section_lines(lines, label, labels):
    pos_map = section_indices(lines, labels)
    if label not in pos_map:
        return []
    start, end = pos_map[label]
    # Trim trailing blank lines
    content = lines[start:end]
    return content

def extract_meta_description_line(lines):
    for ln in lines:
        if ln.startswith("Meta description:"):
            return ln
    return None

def domain_like_count(lines):
    # Count lines that contain at least one domain-like token
    pattern = re.compile(r'\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b', re.IGNORECASE)
    cnt = 0
    for ln in lines:
        if pattern.search(ln):
            cnt += 1
    return cnt

def parse_word_count_target(line):
    # Extract integers from the line and evaluate range
    nums = [int(x) for x in re.findall(r'\d+', line)]
    return nums

def count_urls(lines):
    url_re = re.compile(r'https?://[^\s)]+', re.IGNORECASE)
    cnt = 0
    for ln in lines:
        cnt += len(url_re.findall(ln))
    return cnt

def parse_keywords_csv(path):
    header_ok = False
    rows = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read().splitlines()
        if not raw:
            return header_ok, rows
        # Check exact header
        header_ok = (raw[0].strip() == "keyword,type,intent")
        # Parse CSV for rows after header
        reader = csv.reader(raw[1:])
        for row in reader:
            if not row:
                continue
            # Allow extra whitespace
            row = [col.strip() for col in row]
            # Only consider first three columns if more are present
            if len(row) >= 3:
                rows.append((row[0], row[1], row[2]))
    except Exception:
        return False, []
    return header_ok, rows

def is_json_array_with_schema(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list):
            return False, 0, 0
        if len(data) < 5:
            return False, 0, 0
        # Validate schema and count non-empty h3 arrays
        nonempty_h3 = 0
        for obj in data:
            if not isinstance(obj, dict):
                return False, 0, 0
            if "h2" not in obj or "h3" not in obj:
                return False, 0, 0
            if not isinstance(obj["h2"], str):
                return False, 0, 0
            if not isinstance(obj["h3"], list):
                return False, 0, 0
            if len(obj["h3"]) > 0:
                nonempty_h3 += 1
        return True, len(data), nonempty_h3
    except Exception:
        return False, 0, 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # brief.md checks
        "brief_exists": False,
        "brief_h1_has_2026_and_llm_observability": False,
        "brief_meta_description_length_150_155": False,
        "brief_has_primary_keyword_line": False,
        "brief_secondary_keywords_5_to_10": False,
        "brief_question_keywords_at_least_3": False,
        "brief_lsi_keywords_at_least_5": False,
        "brief_competitors_at_least_3_domains": False,
        "brief_gap_analysis_at_least_3": False,
        "brief_recommended_structure_h2_ge_5_h3_ge_2": False,
        "brief_word_count_target_1500_2500": False,
        "brief_internal_links_at_least_2_urls": False,
        "brief_cta_contains_book_a_demo": False,
        # keywords.csv checks
        "keywords_csv_exists": False,
        "keywords_header_correct": False,
        "keywords_primary_exactly_one_and_contains_llm_observability": False,
        "keywords_secondary_5_to_10": False,
        "keywords_question_at_least_3": False,
        "keywords_lsi_at_least_5": False,
        "keywords_no_duplicate_keywords": False,
        # structure.json checks
        "structure_json_exists": False,
        "structure_json_valid_schema": False,
        "structure_json_min_5_items": False,
        "structure_json_two_nonempty_h3": False,
    }

    # Paths
    brief_path = os.path.join(output_dir, "brief.md")
    keywords_csv_path = os.path.join(output_dir, "keywords.csv")
    structure_json_path = os.path.join(output_dir, "structure.json")

    # Read brief.md
    if os.path.isfile(brief_path):
        checks["brief_exists"] = True
        lines = read_lines(brief_path) or []
        # H1 check
        idx, first_line = find_first_nonempty_line(lines)
        if first_line is not None and first_line.startswith("# "):
            h1_line = first_line
            if ("2026" in h1_line) and ("llm observability" in h1_line.lower()):
                checks["brief_h1_has_2026_and_llm_observability"] = True

        # Meta description line length 150-155 excluding label
        meta_ln = extract_meta_description_line(lines)
        if meta_ln is not None:
            remainder = meta_ln[len("Meta description:"):].strip()
            desc_len = len(remainder)
            if 150 <= desc_len <= 155:
                checks["brief_meta_description_length_150_155"] = True

        # Primary keyword line presence
        for ln in lines:
            if ln.strip().startswith("Primary keyword:"):
                checks["brief_has_primary_keyword_line"] = True
                break

        # Sections mapping
        labels = {
            "Secondary keywords:",
            "Question keywords:",
            "LSI keywords:",
            "Competitors to benchmark:",
            "Competitor gap analysis",
            "Recommended article structure",
            "SEO recommendations",
        }

        secondary_lines = get_section_lines(lines, "Secondary keywords:", labels)
        sec_count = count_bullet_lines(secondary_lines, "- ")
        if 5 <= sec_count <= 10:
            checks["brief_secondary_keywords_5_to_10"] = True

        question_lines = get_section_lines(lines, "Question keywords:", labels)
        q_count = count_bullet_lines(question_lines, "- ")
        if q_count >= 3:
            checks["brief_question_keywords_at_least_3"] = True

        lsi_lines = get_section_lines(lines, "LSI keywords:", labels)
        lsi_count = count_bullet_lines(lsi_lines, "- ")
        if lsi_count >= 5:
            checks["brief_lsi_keywords_at_least_5"] = True

        competitors_lines = get_section_lines(lines, "Competitors to benchmark:", labels)
        if domain_like_count(competitors_lines) >= 3:
            checks["brief_competitors_at_least_3_domains"] = True

        gap_lines = get_section_lines(lines, "Competitor gap analysis", labels)
        gap_count = count_bullet_lines(gap_lines, "- ")
        if gap_count >= 3:
            checks["brief_gap_analysis_at_least_3"] = True

        # Recommended article structure
        struct_lines = get_section_lines(lines, "Recommended article structure", labels)
        h2_count = sum(1 for ln in struct_lines if ln.strip().startswith("H2:"))
        h3_count = sum(1 for ln in struct_lines if ln.strip().startswith("H3:"))
        if h2_count >= 5 and h3_count >= 2:
            checks["brief_recommended_structure_h2_ge_5_h3_ge_2"] = True

        # Word count target
        wct_line = None
        for ln in lines:
            if ln.strip().startswith("Word count target:"):
                wct_line = ln
                break
        if wct_line:
            nums = parse_word_count_target(wct_line)
            # If multiple numbers, ensure min-max within range; if single, ensure within range
            if len(nums) >= 2:
                if min(nums) >= 1500 and max(nums) <= 2500:
                    checks["brief_word_count_target_1500_2500"] = True
            elif len(nums) == 1:
                if 1500 <= nums[0] <= 2500:
                    checks["brief_word_count_target_1500_2500"] = True

        # SEO recommendations: internal links and CTA
        seo_lines = get_section_lines(lines, "SEO recommendations", labels)
        # Find "Internal links" subsection
        il_start = None
        cta_start = None
        for i, ln in enumerate(seo_lines):
            s = ln.strip().lower()
            if il_start is None and s.startswith("internal links"):
                il_start = i
            if cta_start is None and s.startswith("cta"):
                cta_start = i
        # Internal links URL count
        if il_start is not None:
            il_end = len(seo_lines)
            if cta_start is not None and cta_start > il_start:
                il_end = cta_start
            url_count = count_urls(seo_lines[il_start:il_end])
            if url_count >= 2:
                checks["brief_internal_links_at_least_2_urls"] = True
        # CTA contains exact phrase "Book a demo"
        if cta_start is not None:
            cta_end = len(seo_lines)
            # End at next blank line or end of section
            cta_block = seo_lines[cta_start:cta_end]
            cta_text = "\n".join(cta_block)
            if "Book a demo" in cta_text:
                checks["brief_cta_contains_book_a_demo"] = True

    # Parse keywords.csv
    if os.path.isfile(keywords_csv_path):
        checks["keywords_csv_exists"] = True
        header_ok, rows = parse_keywords_csv(keywords_csv_path)
        if header_ok:
            checks["keywords_header_correct"] = True
        # Count by type
        primary_rows = [(k, t, i) for (k, t, i) in rows if t.lower() == "primary"]
        secondary_rows = [(k, t, i) for (k, t, i) in rows if t.lower() == "secondary"]
        question_rows = [(k, t, i) for (k, t, i) in rows if t.lower() == "question"]
        lsi_rows = [(k, t, i) for (k, t, i) in rows if t.lower() == "lsi"]

        # Exactly one primary and keyword contains "LLM observability"
        if len(primary_rows) == 1:
            pk = primary_rows[0][0]
            if "llm observability" in pk.lower():
                checks["keywords_primary_exactly_one_and_contains_llm_observability"] = True

        if 5 <= len(secondary_rows) <= 10:
            checks["keywords_secondary_5_to_10"] = True
        if len(question_rows) >= 3:
            checks["keywords_question_at_least_3"] = True
        if len(lsi_rows) >= 5:
            checks["keywords_lsi_at_least_5"] = True

        # No duplicate keyword strings across all rows (case-insensitive)
        seen = set()
        dup = False
        for (k, t, i) in rows:
            key = k.strip().lower()
            if key in seen:
                dup = True
                break
            seen.add(key)
        if not dup:
            checks["keywords_no_duplicate_keywords"] = True

    # structure.json
    if os.path.isfile(structure_json_path):
        checks["structure_json_exists"] = True
        valid, nitems, nonempty_h3 = is_json_array_with_schema(structure_json_path)
        if valid:
            checks["structure_json_valid_schema"] = True
            if nitems >= 5:
                checks["structure_json_min_5_items"] = True
            if nonempty_h3 >= 2:
                checks["structure_json_two_nonempty_h3"] = True

    # Compute reward
    # Enforce no-op baseline: if any required artifact missing, reward is 0.0
    required_files_exist = checks["brief_exists"] and checks["keywords_csv_exists"] and checks["structure_json_exists"]

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not required_files_exist:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()