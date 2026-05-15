import json
import os
import re
import sys
import csv
from collections import defaultdict, OrderedDict

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def abs_path(root, *parts):
    return os.path.join(root, *parts)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_csv_rows(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for r in reader:
                # Skip completely empty rows
                if len(r) == 0 or all(c.strip() == "" for c in r):
                    continue
                rows.append(r)
    except Exception:
        return None
    return rows

def parse_header(rows):
    if not rows or len(rows) == 0:
        return None
    header = rows[0][:]
    if header:
        header[0] = header[0].lstrip("\ufeff")
    return header

def parse_brief(text):
    # Returns dict with 'location' (str) and 'competitors' (list of str)
    result = {"location": None, "competitors": []}
    if not text:
        return result
    lines = text.splitlines()

    # Extract LOCATION
    loc = None
    for line in lines:
        m = re.match(r"^\s*LOCATION\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
        if m:
            loc = m.group(1).strip()
            break
    result["location"] = loc

    # Extract COMPETITORS
    comp_index = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*COMPETITORS\s*:", line, re.IGNORECASE):
            comp_index = i
            # inline list after colon
            inline = line.split(":", 1)[1].strip()
            tokens = []
            if inline:
                # split on common separators
                parts = re.split(r"[,\|/;]", inline)
                for p in parts:
                    name = p.strip()
                    if name:
                        tokens.append(name)
            # If no inline tokens, parse following bullet lines until blank line
            j = i + 1
            while j < len(lines):
                l = lines[j]
                if l.strip() == "":
                    break
                bullet = re.match(r"^\s*(?:[-*]\s+|\d+[.)]\s+)(.+)$", l)
                if bullet:
                    name = bullet.group(1).strip()
                    if name:
                        tokens.append(name)
                j += 1
            # Clean tokens: strip trailing punctuation
            clean = []
            for t in tokens:
                t = t.strip().strip("•").strip().strip(".;,")
                if t:
                    clean.append(t)
            result["competitors"] = clean
            break

    return result

def normalize_name(s):
    s = (s or "").strip().strip(".;,").lower()
    # if contains URL, extract domain
    s = re.sub(r"\s+", " ", s)
    # Try to extract URL or domain pattern
    url_match = re.search(r"(https?://[^\s\)]+)", s)
    if url_match:
        s = url_match.group(1)
    # Remove surrounding parentheses
    s = s.strip("() ")
    # Remove protocol
    s = re.sub(r"^https?://", "", s)
    # Remove www.
    if s.startswith("www."):
        s = s[4:]
    # If there is a path, keep only the domain
    if "/" in s:
        s = s.split("/")[0]
    # Remove trailing slashes or punctuation
    s = s.strip("/").strip()
    return s

def compare_competitor_sets(expected_list, actual_list):
    # Build normalized sets
    expected_norm = set(normalize_name(x) for x in expected_list if x and x.strip())
    actual_norm = set(normalize_name(x) for x in actual_list if x and x.strip())
    # Remove empty strings
    expected_norm = {x for x in expected_norm if x}
    actual_norm = {x for x in actual_norm if x}
    return expected_norm == actual_norm, expected_norm, actual_norm

def is_int_between(val_str, lo, hi):
    if val_str is None:
        return False
    s = str(val_str).strip()
    if not re.fullmatch(r"-?\d+", s):
        return False
    v = int(s)
    return lo <= v <= hi

def parse_float(val_str):
    try:
        return float(str(val_str).strip())
    except Exception:
        return None

def get_section_bounds(lines, heading_pattern):
    # heading_pattern is a compiled regex to match heading line
    indices = [i for i, l in enumerate(lines) if heading_pattern.match(l)]
    if not indices:
        return None, None
    start = indices[0] + 1
    # Find next heading
    next_head = None
    for i in range(start, len(lines)):
        if re.match(r"^\s{0,3}#{1,6}\s+.+$", lines[i]):
            next_head = i
            break
    end = next_head if next_head is not None else len(lines)
    return start, end

def count_actions_in_section(lines, start, end):
    count = 0
    for i in range(start, end):
        line = lines[i]
        if re.match(r"^\s*-\s+.+", line):
            count += 1
        elif re.match(r"^\s*\d+[.)]\s+.+", line):
            count += 1
    return count

def last_non_empty_line(lines):
    for line in reversed(lines):
        if line.strip() != "":
            return line
    return ""

def main():
    workspace_root = get_workspace_root()
    input_dir = abs_path(workspace_root, "input")
    output_dir = abs_path(workspace_root, "output")

    checks = OrderedDict()

    # Read brief for location and competitors
    brief_path = abs_path(workspace_root, "input", "brief.md")
    brief_text = read_text(brief_path)
    brief_info = parse_brief(brief_text or "")
    location = brief_info.get("location")
    competitors_from_brief = brief_info.get("competitors", [])

    # 1) Seed Keywords
    seed_path = abs_path(output_dir, "seed_keywords.csv")
    checks["seed_exists"] = os.path.isfile(seed_path)
    checks["seed_header_correct"] = False
    checks["seed_min_20"] = False
    checks["seed_min_3_local"] = False
    seed_rows = None
    if checks["seed_exists"]:
        seed_rows = read_csv_rows(seed_path)
        if seed_rows:
            header = parse_header(seed_rows)
            if header == ["keyword", "intent", "estimated monthly searches", "competition level"]:
                checks["seed_header_correct"] = True
            # count data rows
            data_rows = seed_rows[1:] if len(seed_rows) > 1 else []
            checks["seed_min_20"] = len(data_rows) >= 20
            # local keywords: include location or "near me"
            local_count = 0
            city_lower = (location or "").strip().lower() if location else ""
            for r in data_rows:
                if len(r) < 1:
                    continue
                kw = r[0].strip().lower()
                if "near me" in kw or (city_lower and city_lower in kw):
                    local_count += 1
            checks["seed_min_3_local"] = local_count >= 3

    # 2) Keyword Prioritization
    kp_path = abs_path(output_dir, "keyword_prioritization.csv")
    checks["kp_exists"] = os.path.isfile(kp_path)
    checks["kp_header_correct"] = False
    checks["kp_min_15"] = False
    checks["kp_difficulty_valid"] = False
    checks["kp_business_value_valid"] = False
    checks["kp_priority_score_valid"] = False
    checks["kp_top3_condition_met"] = False
    kp_rows = None
    if checks["kp_exists"]:
        kp_rows = read_csv_rows(kp_path)
        if kp_rows:
            header = parse_header(kp_rows)
            if header == ["Keyword", "Monthly Volume", "Difficulty (1-10)", "Business Value", "Priority Score"]:
                checks["kp_header_correct"] = True
            data_rows = kp_rows[1:] if len(kp_rows) > 1 else []
            checks["kp_min_15"] = len(data_rows) >= 15

            # Validate difficulty, business value, priority score
            all_diff_ok = True
            all_bv_ok = True
            all_ps_ok = True
            parsed_rows = []
            for r in data_rows:
                if len(r) < 5:
                    all_diff_ok = False
                    all_bv_ok = False
                    all_ps_ok = False
                    continue
                diff_ok = is_int_between(r[2], 1, 10)
                bv_ok = str(r[3]).strip() in {"High", "Med", "Low"}
                ps = parse_float(r[4])
                ps_ok = (ps is not None and ps > 0)
                all_diff_ok = all_diff_ok and diff_ok
                all_bv_ok = all_bv_ok and bv_ok
                all_ps_ok = all_ps_ok and ps_ok
                # collect for top3 check
                if ps is not None:
                    try:
                        diff_int = int(str(r[2]).strip())
                    except Exception:
                        diff_int = None
                    parsed_rows.append({
                        "ps": ps,
                        "diff": diff_int,
                        "bv": str(r[3]).strip()
                    })
            checks["kp_difficulty_valid"] = all_diff_ok and len(data_rows) > 0
            checks["kp_business_value_valid"] = all_bv_ok and len(data_rows) > 0
            checks["kp_priority_score_valid"] = all_ps_ok and len(data_rows) > 0

            # Top 3 by priority score condition
            if parsed_rows:
                top3 = sorted(parsed_rows, key=lambda x: x["ps"], reverse=True)[:3]
                cond = False
                for row in top3:
                    if row["diff"] is not None and row["diff"] <= 6 and row["bv"] == "High":
                        cond = True
                        break
                checks["kp_top3_condition_met"] = cond

    # 3) Competitor content gap analysis
    comp_path = abs_path(output_dir, "competitor_gap.json")
    checks["comp_exists"] = os.path.isfile(comp_path)
    checks["comp_json_valid"] = False
    checks["comp_array_present"] = False
    checks["comp_count_matches_brief"] = False
    checks["comp_names_match_brief"] = False
    checks["comp_each_has_minimum_lengths"] = False
    comp_data = None
    comp_list = []
    if checks["comp_exists"]:
        try:
            with open(comp_path, "r", encoding="utf-8") as f:
                comp_data = json.load(f)
            checks["comp_json_valid"] = isinstance(comp_data, dict)
            if checks["comp_json_valid"]:
                if "competitors" in comp_data and isinstance(comp_data["competitors"], list):
                    checks["comp_array_present"] = True
                    comp_list = comp_data["competitors"]
                    # Count matches brief
                    if isinstance(competitors_from_brief, list):
                        checks["comp_count_matches_brief"] = len(comp_list) == len(competitors_from_brief)
                    # Names match
                    actual_names = []
                    for c in comp_list:
                        if isinstance(c, dict):
                            name = c.get("name")
                            if isinstance(name, str):
                                actual_names.append(name)
                    equal_sets, expected_norm, actual_norm = compare_competitor_sets(competitors_from_brief, actual_names)
                    checks["comp_names_match_brief"] = equal_sets and checks["comp_count_matches_brief"]
                    # Minimum lengths for each competitor
                    lengths_ok = True
                    for c in comp_list:
                        if not isinstance(c, dict):
                            lengths_ok = False
                            break
                        trk = c.get("top_ranking_keywords")
                        gap = c.get("content_gap_topics")
                        adv = c.get("our_advantages")
                        weak = c.get("weak_spots")
                        if not (isinstance(trk, list) and len(trk) >= 5):
                            lengths_ok = False
                            break
                        if not (isinstance(gap, list) and len(gap) >= 5):
                            lengths_ok = False
                            break
                        if not isinstance(adv, list):
                            lengths_ok = False
                            break
                        if not (isinstance(weak, list) and len(weak) >= 3):
                            lengths_ok = False
                            break
                    checks["comp_each_has_minimum_lengths"] = lengths_ok and len(comp_list) == len(competitors_from_brief)
        except Exception:
            checks["comp_json_valid"] = False

    # 4) Content roadmap
    roadmap_path = abs_path(output_dir, "content_roadmap.csv")
    checks["roadmap_exists"] = os.path.isfile(roadmap_path)
    checks["roadmap_header_correct"] = False
    checks["roadmap_min_24"] = False
    checks["roadmap_months_valid"] = False
    checks["roadmap_theme_matches_months"] = False
    checks["roadmap_each_month_min2"] = False
    roadmap_rows = None
    if checks["roadmap_exists"]:
        roadmap_rows = read_csv_rows(roadmap_path)
        if roadmap_rows:
            header = parse_header(roadmap_rows)
            if header == ["Month", "Theme", "Content Type", "Working Title", "Target Keywords", "Notes"]:
                checks["roadmap_header_correct"] = True
            data_rows = roadmap_rows[1:] if len(roadmap_rows) > 1 else []
            checks["roadmap_min_24"] = len(data_rows) >= 24

            # Validate months 1-12 and theme mapping
            months_valid = True
            theme_mapping_ok = True
            month_counts = defaultdict(int)
            for r in data_rows:
                if len(r) < 2:
                    months_valid = False
                    theme_mapping_ok = False
                    continue
                m_str = str(r[0]).strip()
                t_raw = str(r[1]).strip()
                # month int 1..12
                if not re.fullmatch(r"\d+", m_str):
                    months_valid = False
                    continue
                m_val = int(m_str)
                if not (1 <= m_val <= 12):
                    months_valid = False
                # Theme normalization
                t_norm = t_raw.split("(")[0].strip()
                if m_val in (1, 2, 3):
                    if t_norm != "Foundation":
                        theme_mapping_ok = False
                elif m_val in (4, 5, 6):
                    if t_norm != "Authority Building":
                        theme_mapping_ok = False
                else:
                    if t_norm != "Competitive Keywords":
                        theme_mapping_ok = False
                if 1 <= m_val <= 12:
                    month_counts[m_val] += 1
            checks["roadmap_months_valid"] = months_valid and len(data_rows) > 0
            checks["roadmap_theme_matches_months"] = theme_mapping_ok and len(data_rows) > 0
            # At least 2 rows per month
            all_months_min2 = all(month_counts.get(m, 0) >= 2 for m in range(1, 13))
            checks["roadmap_each_month_min2"] = all_months_min2

    # 5) On-page checklist
    onpage_path = abs_path(output_dir, "onpage_checklist.md")
    checks["onpage_exists"] = os.path.isfile(onpage_path)
    checks["onpage_has_title_tag_heading"] = False
    checks["onpage_has_meta_description_heading"] = False
    checks["onpage_has_content_structure_heading"] = False
    checks["onpage_has_technical_basics_heading"] = False
    checks["onpage_checkboxes_per_heading"] = False
    checks["onpage_mentions_keyword_density"] = False
    if checks["onpage_exists"]:
        txt = read_text(onpage_path) or ""
        lines = txt.splitlines()
        # Headings regex
        h_title = re.compile(r"^\s{0,3}#{1,6}\s*Title Tag\s*$")
        h_meta = re.compile(r"^\s{0,3}#{1,6}\s*Meta Description\s*$")
        h_struct = re.compile(r"^\s{0,3}#{1,6}\s*Content Structure\s*$")
        h_tech = re.compile(r"^\s{0,3}#{1,6}\s*Technical Basics\s*$")

        idx_title = get_section_bounds(lines, h_title)
        idx_meta = get_section_bounds(lines, h_meta)
        idx_struct = get_section_bounds(lines, h_struct)
        idx_tech = get_section_bounds(lines, h_tech)

        checks["onpage_has_title_tag_heading"] = idx_title != (None, None)
        checks["onpage_has_meta_description_heading"] = idx_meta != (None, None)
        checks["onpage_has_content_structure_heading"] = idx_struct != (None, None)
        checks["onpage_has_technical_basics_heading"] = idx_tech != (None, None)

        # Count checkboxes under each heading
        def count_checkboxes(bounds):
            if bounds == (None, None):
                return 0
            s, e = bounds
            cnt = 0
            for i in range(s, e):
                if re.match(r"^\s*-\s*\[\s*\]\s+.+", lines[i]):
                    cnt += 1
            return cnt

        c1 = count_checkboxes(idx_title)
        c2 = count_checkboxes(idx_meta)
        c3 = count_checkboxes(idx_struct)
        c4 = count_checkboxes(idx_tech)
        checks["onpage_checkboxes_per_heading"] = (c1 >= 3 and c2 >= 3 and c3 >= 3 and c4 >= 3)

        # Mention keyword density "1-2%"
        checks["onpage_mentions_keyword_density"] = ("1-2%" in txt)

    # 6) Local SEO strategy
    local_path = abs_path(output_dir, "local_seo_strategy.md")
    checks["local_exists"] = os.path.isfile(local_path)
    checks["local_has_gbp_heading"] = False
    checks["local_has_citations_heading"] = False
    checks["local_mentions_location"] = False
    checks["local_gbp_min5_actions"] = False
    checks["local_citations_min5_actions"] = False
    if checks["local_exists"]:
        txt = read_text(local_path) or ""
        lines = txt.splitlines()
        h_gbp = re.compile(r"^\s{0,3}#{1,6}\s*Google Business Profile Optimization\s*$")
        h_cit = re.compile(r"^\s{0,3}#{1,6}\s*Local Citation Building\s*$")
        gbp_bounds = get_section_bounds(lines, h_gbp)
        cit_bounds = get_section_bounds(lines, h_cit)
        checks["local_has_gbp_heading"] = gbp_bounds != (None, None)
        checks["local_has_citations_heading"] = cit_bounds != (None, None)

        # location mention
        loc_lower = (location or "").strip().lower()
        if loc_lower:
            checks["local_mentions_location"] = loc_lower in (txt.lower())
        else:
            checks["local_mentions_location"] = False

        # count actions
        if gbp_bounds != (None, None):
            gbp_actions = count_actions_in_section(lines, gbp_bounds[0], gbp_bounds[1])
            checks["local_gbp_min5_actions"] = gbp_actions >= 5
        if cit_bounds != (None, None):
            cit_actions = count_actions_in_section(lines, cit_bounds[0], cit_bounds[1])
            checks["local_citations_min5_actions"] = cit_actions >= 5

    # 7) Monthly tracking template
    tracking_path = abs_path(output_dir, "monthly_tracking_template.csv")
    checks["tracking_exists"] = os.path.isfile(tracking_path)
    checks["tracking_header_correct"] = False
    if checks["tracking_exists"]:
        tr_rows = read_csv_rows(tracking_path)
        if tr_rows:
            header = parse_header(tr_rows)
            if header == ["PERIOD", "TOP 5 RANKING KEYWORDS", "NEW KEYWORDS RANKING", "ORGANIC TRAFFIC", "TOP PERFORMING PAGES", "NEXT MONTH FOCUS"]:
                checks["tracking_header_correct"] = True

    # 8) Deliverables summary
    deliv_path = abs_path(output_dir, "deliverables.json")
    checks["deliverables_exists"] = os.path.isfile(deliv_path)
    checks["deliverables_json_valid"] = False
    checks["deliverables_has_keys"] = False
    checks["deliverables_counts_match"] = False
    deliv = None
    if checks["deliverables_exists"]:
        try:
            with open(deliv_path, "r", encoding="utf-8") as f:
                deliv = json.load(f)
            checks["deliverables_json_valid"] = isinstance(deliv, dict)
            if checks["deliverables_json_valid"]:
                required_keys = {"number_of_seed_keywords", "number_of_prioritized_keywords", "number_of_competitors", "number_of_roadmap_items"}
                checks["deliverables_has_keys"] = required_keys.issubset(set(deliv.keys()))
                # Compute counts from actual files
                seed_count = 0
                kp_count = 0
                comp_count = 0
                roadmap_count = 0
                if seed_rows is None and os.path.isfile(seed_path):
                    seed_rows = read_csv_rows(seed_path)
                if seed_rows and len(seed_rows) > 1:
                    seed_count = len(seed_rows) - 1
                if kp_rows is None and os.path.isfile(kp_path):
                    kp_rows = read_csv_rows(kp_path)
                if kp_rows and len(kp_rows) > 1:
                    kp_count = len(kp_rows) - 1
                if comp_list is None and os.path.isfile(comp_path):
                    try:
                        with open(comp_path, "r", encoding="utf-8") as f:
                            comp_data2 = json.load(f)
                        comp_list = comp_data2.get("competitors", []) if isinstance(comp_data2, dict) else []
                    except Exception:
                        comp_list = []
                if comp_list:
                    comp_count = len(comp_list)
                if roadmap_rows is None and os.path.isfile(roadmap_path):
                    roadmap_rows = read_csv_rows(roadmap_path)
                if roadmap_rows and len(roadmap_rows) > 1:
                    roadmap_count = len(roadmap_rows) - 1

                if checks["deliverables_has_keys"]:
                    try:
                        match = (
                            int(deliv["number_of_seed_keywords"]) == seed_count and
                            int(deliv["number_of_prioritized_keywords"]) == kp_count and
                            int(deliv["number_of_competitors"]) == comp_count and
                            int(deliv["number_of_roadmap_items"]) == roadmap_count
                        )
                        checks["deliverables_counts_match"] = match
                    except Exception:
                        checks["deliverables_counts_match"] = False
        except Exception:
            checks["deliverables_json_valid"] = False

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure reward is between 0 and 1
    reward = max(0.0, min(1.0, float(reward)))

    # Output JSON with "reward" first
    result = OrderedDict()
    result["reward"] = reward
    for k, v in checks.items():
        result[k] = bool(v)

    print(json.dumps(result))

if __name__ == "__main__":
    main()