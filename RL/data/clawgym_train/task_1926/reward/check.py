import json
import os
import re
import sys
import csv

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def get_lines_between_sections(lines, section_title):
    # Find a section by heading containing section_title (case-insensitive) starting with "## " or "# "
    start_idx = None
    pattern = re.compile(r'^\s*##\s+' + re.escape(section_title) + r'\b', re.IGNORECASE)
    pattern_h1 = re.compile(r'^\s*#\s+' + re.escape(section_title) + r'\b', re.IGNORECASE)
    for i, l in enumerate(lines):
        if pattern.search(l) or pattern_h1.search(l):
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    # End at next "## " or "# " heading (but allow "### " inside the section)
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if re.match(r'^\s*#\s+', lines[j]) and not re.match(r'^\s*###\s+', lines[j]):
            end_idx = j
            break
        if re.match(r'^\s*##\s+', lines[j]):
            end_idx = j
            break
    return lines[start_idx:end_idx]

def extract_tagline_from_yaml(yaml_text):
    if not yaml_text:
        return None
    # Simple single-line tagline extraction
    for line in yaml_text.splitlines():
        if re.match(r'^\s*tagline\s*:', line):
            val = line.split(':', 1)[1].strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            return val
    return None

def parse_competitors(csv_text):
    names = set()
    if not csv_text:
        return names
    try:
        reader = csv.reader(csv_text.splitlines())
        rows = list(reader)
        for idx, row in enumerate(rows):
            if not row:
                continue
            for cell in row:
                c = (cell or "").strip()
                if not c:
                    continue
                # Skip header-like cells
                low = c.lower()
                if low in ("competitor", "name", "competitors", "names"):
                    continue
                names.add(c)
            # If first row likely header, skip it by removing generic header terms already filtered
        return names
    except Exception:
        # Fallback: split by commas and newlines
        for part in re.split(r'[,\n]+', csv_text):
            p = part.strip()
            if p and p.lower() not in ("competitor", "name", "competitors", "names"):
                names.add(p)
        return names

def count_thread_blocks(section_lines):
    indices = [i for i, l in enumerate(section_lines) if re.match(r'^\s*###\s*Thread\s*:', l)]
    return indices

def block_slice(section_lines, start_idx, next_start_idx=None):
    end = len(section_lines) if next_start_idx is None else next_start_idx
    return section_lines[start_idx:end]

def find_checkbox_presence(subsection_lines):
    return any(re.match(r'^\s*-\s*\[\s*\]\s+', l) for l in subsection_lines)

def find_subsection_lines(section_lines, subheading):
    # Find "### subheading" within given section_lines
    start = None
    for i, l in enumerate(section_lines):
        if re.match(r'^\s*###\s+' + re.escape(subheading) + r'\b', l, re.IGNORECASE):
            start = i + 1
            break
    if start is None:
        return []
    # End at next "### " or end of this section
    end = len(section_lines)
    for j in range(start, len(section_lines)):
        if re.match(r'^\s*###\s+', section_lines[j]):
            end = j
            break
    return section_lines[start:end]

def url_in_line(line):
    # Accepts lines like "**URL:** https://..." or "URL: http://..."
    m = re.search(r'https?://\S+', line)
    return m.group(0) if m else None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    plan_path = os.path.join(output_dir, "docs", "outreach-plan.md")
    drafts_path = os.path.join(output_dir, "drafts.json")
    branding_path = os.path.join(input_dir, "branding.yaml")
    competitors_path = os.path.join(input_dir, "competitors.csv")

    checks = {
        "has_outreach_plan_file": False,
        "heading_contains_product_and_phrase": False,
        "target_communities_table_ok": False,
        "top_threads_five_with_requirements": False,
        "ph_checklist_and_tagline_ok": False,
        "search_keywords_and_competitors_ok": False,
        "has_drafts_file": False,
        "drafts_json_valid_and_diverse": False,
    }

    plan_text = read_file(plan_path)
    if plan_text and plan_text.strip():
        checks["has_outreach_plan_file"] = True

    # Heading with "Community Outreach Plan" and "LiteTrace"
    if checks["has_outreach_plan_file"]:
        heading_lines = [ln for ln in plan_text.splitlines() if ln.strip().startswith("#")]
        found_heading = False
        for ln in heading_lines:
            if ("community outreach plan" in ln.lower()) and ("litetrace".lower() in ln.lower()):
                found_heading = True
                break
        checks["heading_contains_product_and_phrase"] = found_heading

    # Target Communities table detection
    if checks["has_outreach_plan_file"]:
        lines = plan_text.splitlines()
        tc_section = get_lines_between_sections(lines, "Target Communities")
        if tc_section:
            # Find header line with '|' and containing 'Community' and 'Priority'
            header_idx = None
            for i, l in enumerate(tc_section):
                if '|' in l and ('community' in l.lower()) and ('priority' in l.lower()):
                    header_idx = i
                    break
            if header_idx is not None:
                # Count data rows after header (exclude separator '---' lines)
                data_count = 0
                for l in tc_section[header_idx+1:]:
                    if re.match(r'^\s*$', l):
                        continue
                    if '|' in l and '---' not in l and ('community' not in l.lower() or 'priority' not in l.lower()):
                        data_count += 1
                if data_count >= 3:
                    checks["target_communities_table_ok"] = True

    # Top Threads to Engage section
    if checks["has_outreach_plan_file"]:
        lines = plan_text.splitlines()
        tt_section = get_lines_between_sections(lines, "Top Threads to Engage")
        if tt_section:
            thread_indices = count_thread_blocks(tt_section)
            if len(thread_indices) == 5:
                blocks_ok = True
                disclaimers_total = 0
                for idx_i, start in enumerate(thread_indices):
                    next_start = thread_indices[idx_i + 1] if idx_i + 1 < len(thread_indices) else None
                    block_lines = block_slice(tt_section, start, next_start)
                    block_text = "\n".join(block_lines)
                    # URL line check
                    url_line_ok = False
                    community_line_ok = False
                    disclaimer_present = False
                    for bl in block_lines:
                        # Normalize to catch "**URL:**" formatting or plain "URL:"
                        bl_stripped = bl.strip()
                        # Check for URL line starting with URL:
                        if re.match(r'^\s*\*{0,2}\s*URL\s*:', bl, re.IGNORECASE):
                            if url_in_line(bl):
                                url_line_ok = True
                        # Community/Subreddit line
                        if re.search(r'\bcommunity\b', bl, re.IGNORECASE) or re.search(r'\bsubreddit\b', bl, re.IGNORECASE):
                            community_line_ok = True
                    if re.search(r'disclaimer', block_text, re.IGNORECASE):
                        disclaimer_present = True
                        disclaimers_total += len(re.findall(r'disclaimer', block_text, re.IGNORECASE))
                    if not (url_line_ok and community_line_ok and disclaimer_present):
                        blocks_ok = False
                        break
                if blocks_ok and disclaimers_total >= 5:
                    checks["top_threads_five_with_requirements"] = True

    # ProductHunt Launch Checklist and tagline
    if checks["has_outreach_plan_file"]:
        lines = plan_text.splitlines()
        ph_section = get_lines_between_sections(lines, "ProductHunt Launch Checklist")
        tagline_text = None
        branding_text = read_file(branding_path)
        tagline_text = extract_tagline_from_yaml(branding_text) if branding_text else None
        if ph_section:
            # Subsections
            pre_lines = find_subsection_lines(ph_section, "Pre-Launch")
            launch_lines = find_subsection_lines(ph_section, "Launch Day")
            post_lines = find_subsection_lines(ph_section, "Post-Launch")
            subs_ok = bool(pre_lines) and bool(launch_lines) and bool(post_lines)
            checkboxes_ok = find_checkbox_presence(pre_lines) and find_checkbox_presence(launch_lines) and find_checkbox_presence(post_lines)
            tagline_ok = False
            if tagline_text:
                if tagline_text in plan_text:
                    tagline_ok = True
            # If tagline could not be parsed, treat as not ok
            if subs_ok and checkboxes_ok and tagline_ok:
                checks["ph_checklist_and_tagline_ok"] = True

    # Search Keywords Used section and competitors in document
    if checks["has_outreach_plan_file"]:
        lines = plan_text.splitlines()
        sk_section = get_lines_between_sections(lines, "Search Keywords Used")
        has_sk_section = len(sk_section) > 0
        competitors_text = read_file(competitors_path)
        comp_names = parse_competitors(competitors_text or "")
        found_comps = set()
        plan_low = plan_text.lower()
        for name in comp_names:
            nlow = name.lower()
            if nlow and nlow in plan_low:
                found_comps.add(name)
        if has_sk_section and len(found_comps) >= 2:
            checks["search_keywords_and_competitors_ok"] = True

    # Drafts JSON checks
    if os.path.isfile(drafts_path):
        checks["has_drafts_file"] = True
        try:
            with open(drafts_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            valid = isinstance(data, list) and len(data) == 5
            url_re = re.compile(r'^https?://[^\s]+$')
            communities = []
            if valid:
                for item in data:
                    if not isinstance(item, dict):
                        valid = False
                        break
                    keys_ok = all(k in item for k in ["title", "url", "community", "why_relevant", "draft"])
                    if not keys_ok:
                        valid = False
                        break
                    if not isinstance(item.get("url"), str) or not url_re.match(item.get("url", "")):
                        valid = False
                        break
                    communities.append(str(item.get("community", "")))
            if valid:
                # Diversity checks
                distinct = set([c.strip().lower() for c in communities if c.strip()])
                has_reddit = any(("reddit" in c or "r/" in c) for c in [c.lower() for c in communities])
                has_hn_or_ph = any(("hacker news" in c.lower()) or ("producthunt" in c.lower()) or ("product hunt" in c.lower()) for c in communities)
                if len(distinct) >= 2 and has_reddit and has_hn_or_ph:
                    checks["drafts_json_valid_and_diverse"] = True
        except Exception:
            checks["drafts_json_valid_and_diverse"] = False
    else:
        checks["has_drafts_file"] = False
        checks["drafts_json_valid_and_diverse"] = False

    # Compute reward
    # Baseline gating: require both core artifacts to exist to award any credit
    gating_ok = checks["has_outreach_plan_file"] and checks["has_drafts_file"]
    # Count total checks excluding gating logic? All booleans are concrete points.
    check_keys = [k for k in checks.keys()]
    total_points = len(check_keys)
    passed_points = sum(1 for k in check_keys if checks[k])
    reward = 0.0
    if gating_ok:
        # Reward is fraction of passed concrete checks
        reward = passed_points / total_points if total_points > 0 else 0.0
    else:
        reward = 0.0

    # Clamp to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()