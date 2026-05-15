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

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_jsonl_sources(path):
    sources = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    if isinstance(obj, dict):
                        for key in ("source", "source_name", "publisher", "publication", "author", "organization"):
                            val = obj.get(key)
                            if isinstance(val, str) and val.strip():
                                sources.add(val.strip())
                except Exception:
                    continue
    except Exception:
        pass
    return sources

def parse_simple_yaml(path):
    # Minimal YAML mapping parser supporting nested dictionaries by indentation
    root = {}
    stack = [(-1, root)]
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                # Remove comments (# ...) only when not inside quotes
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                # Inline comments: split on ' #' if there is a space before
                # but safer: remove trailing comments starting with ' #'
                # If the line starts with '#', skip
                if line.lstrip().startswith("#"):
                    continue
                # Keep full content; YAML comments can appear after values, but we will not over-handle
                # Determine indent
                indent = len(line) - len(line.lstrip(" "))
                # Pop stack for dedent
                while stack and indent <= stack[-1][0]:
                    stack.pop()
                if not stack:
                    stack = [(-1, root)]
                parent = stack[-1][1]
                # Split key: value
                if ":" not in line:
                    # Not a key-value; ignore
                    continue
                key_part, val_part = line.lstrip().split(":", 1)
                key = key_part.strip()
                val = val_part.strip()
                if not key:
                    continue
                if val == "":
                    # Start nested dict
                    new_dict = {}
                    parent[key] = new_dict
                    stack.append((indent, new_dict))
                else:
                    # Parse scalar
                    parsed = parse_yaml_scalar(val)
                    parent[key] = parsed
        return root
    except Exception:
        return {}

def parse_yaml_scalar(val):
    # Remove quotes
    v = val.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
        return v
    # Booleans
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    # Null
    if low in ("null", "none", "~"):
        return None
    # Int
    try:
        if re.fullmatch(r"[+-]?\d+", v):
            return int(v)
    except Exception:
        pass
    # Float
    try:
        if re.fullmatch(r"[+-]?\d+\.\d+", v):
            return float(v)
    except Exception:
        pass
    return v

def find_section_indices(lines, header_substrings):
    # Returns dict of header -> line index if found
    idxs = {}
    for i, line in enumerate(lines):
        for h in header_substrings:
            if h not in idxs and h in line:
                idxs[h] = i
    return idxs

def get_section_text(lines, start_idx, end_idx):
    if start_idx is None:
        return ""
    end = end_idx if end_idx is not None else len(lines)
    if start_idx >= end:
        return ""
    return "\n".join(lines[start_idx:end])

def tokenize_words(s):
    # words are alphanumeric or underscore/apostrophe
    return re.findall(r"\b[\w']+\b", s)

def count_words(s):
    return len(tokenize_words(s))

def count_hashtags(s):
    # tokens starting with '#'
    return len(re.findall(r"(?:^|\s)#\w+", s))

def extract_hashtags_by_tier(section_text):
    lines = section_text.splitlines()
    # Find tier headers
    headers = [
        "Niche (under 100K)",
        "Mid (100K-1M)",
        "Large (1M+)"
    ]
    positions = {}
    for i, line in enumerate(lines):
        for h in headers:
            if h in line:
                positions[h] = i
    tiers_counts = {h: 0 for h in headers}
    # Determine ranges for each header
    ordered_headers = [h for h in headers if h in positions]
    ordered_headers.sort(key=lambda h: positions[h])
    for idx, h in enumerate(ordered_headers):
        start = positions[h] + 1
        end = positions[ordered_headers[idx+1]] if idx + 1 < len(ordered_headers) else len(lines)
        block = "\n".join(lines[start:end])
        tiers_counts[h] = count_hashtags(block)
    return tiers_counts, set(ordered_headers) == set(headers)

def parse_slides_section(slides_text):
    # Returns list of slide blocks with fields
    lines = slides_text.splitlines()
    slide_indices = []
    for i, line in enumerate(lines):
        if re.match(r"^\s*Slide\s+\d+:\s*", line):
            slide_indices.append(i)
    slide_blocks = []
    for idx, start in enumerate(slide_indices):
        end = slide_indices[idx+1] if idx + 1 < len(slide_indices) else len(lines)
        block_lines = lines[start:end]
        slide_blocks.append(block_lines)
    return slide_blocks

def find_label_block(lines, label):
    # Find a label like "Headline:", "Body text:", etc.
    # return tuple (line_index, content_on_same_line, following_lines_until_next_label_or_end)
    pattern = re.compile(r"^\s*-?\s*"+re.escape(label)+r"\s*:\s*(.*)$", re.IGNORECASE)
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            same_line = m.group(1).rstrip()
            # Collect following lines until next label or end or next "Slide"
            following = []
            for j in range(i+1, len(lines)):
                nxt = lines[j]
                if re.match(r"^\s*-?\s*(Headline|Body text|Visual direction|Transition hook)\s*:", nxt, re.IGNORECASE):
                    break
                if re.match(r"^\s*Slide\s+\d+:", nxt):
                    break
                following.append(nxt.rstrip())
            return i, same_line, following
    return None, "", []

def clean_headline_text(text, following):
    # If same_line text empty, consider first following non-empty line as headline content
    if text.strip():
        candidate = text.strip()
    else:
        candidate = ""
        for ln in following:
            if ln.strip():
                candidate = ln.strip()
                break
    return candidate

def compute_body_lines_count(same_line, following):
    # Body text expected in subsequent lines mostly; count non-empty lines in following
    # But if same_line has content, count it as one line.
    lines = []
    if same_line.strip():
        lines.append(same_line.strip())
    for ln in following:
        if ln.strip():
            lines.append(ln.strip())
    return len(lines)

def has_nonempty_transition_hook(same_line, following):
    if same_line.strip():
        return True
    for ln in following:
        if ln.strip():
            return True
    return False

def check_platform(md_text, platform_name, reqs, banned_words_ci, allowed_sources):
    # Initialize results
    results = {
        "file_exists": False,
        "order_ok": False,
        "slide_count_ok": False,
        "slides_fields_ok": False,
        "headline_lengths_ok": False,
        "body_lines_ok": False,
        "transition_hooks_ratio_ok": False,
        "cover_options_ok": False,
        "cta_options_ok": False,
        "caption_range_ok": False,
        "hashtags_tiers_ok": False,
        "dimensions_string_ok": False,
        "citation_present_ok": False,
        "banned_words_absent": False,
        # values for metadata cross-check
        "computed": {}
    }
    if not md_text:
        return results
    results["file_exists"] = True
    # Lines processing
    lines = md_text.splitlines()
    # Section order
    headers = [
        "Cover Slide (3 Options",
        "Slide-by-Slide Script",
        "CTA Slide (3 Options",
        "Post Caption",
        "Hashtag Set",
        "Design Tips"
    ]
    idx_map = {}
    for h in headers:
        idx = next((i for i, line in enumerate(lines) if h in line), None)
        idx_map[h] = idx
    if all(idx_map[h] is not None for h in headers):
        order = [idx_map[h] for h in headers]
        if order == sorted(order):
            results["order_ok"] = True
    # Extract sections
    cover_section = get_section_text(
        lines,
        idx_map.get(headers[0]),
        idx_map.get(headers[1])
    )
    slides_section = get_section_text(
        lines,
        idx_map.get(headers[1]),
        idx_map.get(headers[2])
    )
    cta_section = get_section_text(
        lines,
        idx_map.get(headers[2]),
        idx_map.get(headers[3])
    )
    caption_section = get_section_text(
        lines,
        idx_map.get(headers[3]),
        idx_map.get(headers[4])
    )
    hashtags_section = get_section_text(
        lines,
        idx_map.get(headers[4]),
        idx_map.get(headers[5])
    )
    tips_section = get_section_text(
        lines,
        idx_map.get(headers[5]),
        None
    )
    # Slide count requirement
    expected_slides = None
    slide_counts = reqs.get("slide_counts") or reqs.get("slides") or {}
    if isinstance(slide_counts, dict):
        expected_slides = slide_counts.get(platform_name)
    if expected_slides is None:
        # Fallback defaults
        expected_slides = 10 if platform_name == "linkedin" else 9
    slide_headers = re.findall(r"^\s*Slide\s+\d+:\s*", slides_section, flags=re.MULTILINE)
    actual_slide_count = len(slide_headers)
    if actual_slide_count == expected_slides:
        results["slide_count_ok"] = True
    results["computed"]["slide_count"] = actual_slide_count
    # Per-slide fields
    slide_blocks = parse_slides_section(slides_section)
    all_fields_present = True
    headline_lengths_ok = True
    body_lines_ok = True
    hooks_with_content = 0
    headline_limit = reqs.get("headline_max_words", 8)
    for block in slide_blocks:
        # Headline
        hi, h_same, h_follow = find_label_block(block, "Headline")
        bi, b_same, b_follow = find_label_block(block, "Body text")
        vi, v_same, v_follow = find_label_block(block, "Visual direction")
        ti, t_same, t_follow = find_label_block(block, "Transition hook")
        if hi is None or bi is None or vi is None or ti is None:
            all_fields_present = False
            # continue to collect other metrics but flag failure
        # Headline word limit
        headline_text = clean_headline_text(h_same or "", h_follow or [])
        # Count words ignoring punctuation
        h_words = tokenize_words(headline_text)
        if len(h_words) > headline_limit:
            headline_lengths_ok = False
        # Body lines count 2-4
        body_count = compute_body_lines_count(b_same or "", b_follow or [])
        if not (2 <= body_count <= 4):
            body_lines_ok = False
        # Transition hook presence
        if has_nonempty_transition_hook(t_same or "", t_follow or []):
            hooks_with_content += 1
    results["slides_fields_ok"] = all_fields_present and (actual_slide_count > 0)
    results["headline_lengths_ok"] = headline_lengths_ok and (actual_slide_count > 0)
    results["body_lines_ok"] = body_lines_ok and (actual_slide_count > 0)
    # Transition hook ratio
    min_ratio = reqs.get("transition_hook_min_ratio") or reqs.get("transition_ratio") or 0.5
    needed = int((expected_slides if expected_slides else actual_slide_count) * min_ratio)
    # ceil
    if (expected_slides if expected_slides else actual_slide_count) * min_ratio != int((expected_slides if expected_slides else actual_slide_count) * min_ratio):
        needed = int((expected_slides if expected_slides else actual_slide_count) * min_ratio) + 1
    if actual_slide_count > 0 and hooks_with_content >= needed:
        results["transition_hooks_ratio_ok"] = True
    results["computed"]["transition_hooks_with_content"] = hooks_with_content
    results["computed"]["transition_hooks_needed"] = needed
    # Cover options count
    cover_opts = set()
    for m in re.finditer(r"Option\s+([ABC])", cover_section):
        cover_opts.add(m.group(1))
    results["cover_options_ok"] = cover_opts == {"A", "B", "C"}
    results["computed"]["cover_options"] = len(cover_opts)
    # CTA options count
    cta_opts = set()
    for m in re.finditer(r"Option\s+([ABC])", cta_section):
        cta_opts.add(m.group(1))
    results["cta_options_ok"] = cta_opts == {"A", "B", "C"}
    results["computed"]["cta_options"] = len(cta_opts)
    # Caption word count
    cap_words = count_words(caption_section)
    cap_range = reqs.get("caption_word_range") or reqs.get("caption") or {}
    cap_min = None
    cap_max = None
    if isinstance(cap_range, dict):
        cap_min = cap_range.get("min", 150)
        cap_max = cap_range.get("max", 300)
    else:
        cap_min, cap_max = 150, 300
    if cap_min is None: cap_min = 150
    if cap_max is None: cap_max = 300
    if cap_min <= cap_words <= cap_max:
        results["caption_range_ok"] = True
    results["computed"]["caption_word_count"] = cap_words
    # Hashtags tiers
    tiers_counts, all_headers_present = extract_hashtags_by_tier(hashtags_section)
    # Determine expected per-tier count
    hashtags_cfg = (reqs.get("hashtags_by_tier") or reqs.get("hashtag_tiers") or reqs.get("hashtags") or {})
    per_tier_niche = None
    per_tier_mid = None
    per_tier_large = None
    if isinstance(hashtags_cfg, dict) and any(k in hashtags_cfg for k in ("niche", "mid", "large")):
        per_tier_niche = hashtags_cfg.get("niche", 10)
        per_tier_mid = hashtags_cfg.get("mid", 10)
        per_tier_large = hashtags_cfg.get("large", 10)
    elif isinstance(hashtags_cfg, dict) and "per_tier" in hashtags_cfg:
        per_tier_niche = per_tier_mid = per_tier_large = hashtags_cfg.get("per_tier", 10)
    else:
        # default
        per_tier_niche = per_tier_mid = per_tier_large = 10
    # Validation: each tier at least required, and total exactly sum
    niche_cnt = tiers_counts.get("Niche (under 100K)", 0)
    mid_cnt = tiers_counts.get("Mid (100K-1M)", 0)
    large_cnt = tiers_counts.get("Large (1M+)", 0)
    expected_total = (per_tier_niche or 0) + (per_tier_mid or 0) + (per_tier_large or 0)
    tiers_ok = (all_headers_present and
                niche_cnt >= (per_tier_niche or 0) and
                mid_cnt >= (per_tier_mid or 0) and
                large_cnt >= (per_tier_large or 0) and
                (niche_cnt + mid_cnt + large_cnt) == expected_total)
    results["hashtags_tiers_ok"] = tiers_ok
    results["computed"]["hashtags_by_tier"] = {
        "niche": niche_cnt,
        "mid": mid_cnt,
        "large": large_cnt
    }
    # Dimensions string
    dims_substring = "Recommended dimensions: LinkedIn: 1080x1080; Instagram: 1080x1350"
    results["dimensions_string_ok"] = (dims_substring in tips_section)
    # Citation presence
    citations = re.findall(r"\[Source:\s*([^\]]+)\]", md_text)
    citation_ok = False
    if citations and allowed_sources:
        for c in citations:
            if c.strip() in allowed_sources:
                citation_ok = True
                break
    results["citation_present_ok"] = citation_ok
    # Banned words absent
    banned_ok = True
    for bw in banned_words_ci:
        # word boundary match, case-insensitive
        pattern = re.compile(r"\b" + re.escape(bw) + r"\b", re.IGNORECASE)
        if pattern.search(md_text):
            banned_ok = False
            break
    results["banned_words_absent"] = banned_ok
    # For metadata: headline_max_words from requirements
    results["computed"]["headline_max_words"] = headline_limit
    return results

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Read inputs
    brief_path = os.path.join(input_dir, "brief.json")
    quotes_path = os.path.join(input_dir, "quotes.jsonl")
    reqs_path = os.path.join(input_dir, "requirements.yaml")
    brief = read_json(brief_path) or {}
    banned_words = brief.get("banned_words") if isinstance(brief, dict) else None
    if not isinstance(banned_words, list):
        banned_words = []
    # Normalize banned words for case-insensitive search
    banned_words_ci = [w.strip() for w in banned_words if isinstance(w, str) and w.strip()]
    allowed_sources = parse_jsonl_sources(quotes_path)
    reqs = parse_simple_yaml(reqs_path)
    # Files to check
    linkedin_path = os.path.join(output_dir, "linkedin_carousel.md")
    instagram_path = os.path.join(output_dir, "instagram_carousel.md")
    metadata_path = os.path.join(output_dir, "metadata.json")
    linkedin_text = read_text(linkedin_path)
    instagram_text = read_text(instagram_path)
    metadata_obj = read_json(metadata_path)
    # Compute per-platform checks
    linkedin = check_platform(linkedin_text, "linkedin", reqs, banned_words_ci, allowed_sources)
    instagram = check_platform(instagram_text, "instagram", reqs, banned_words_ci, allowed_sources)
    # Metadata cross-check
    metadata_valid_json = isinstance(metadata_obj, dict)
    metadata_matches_linkedin = False
    metadata_matches_instagram = False
    if metadata_valid_json:
        # keys present
        for platform, res in [("linkedin", linkedin), ("instagram", instagram)]:
            if platform in metadata_obj and isinstance(metadata_obj[platform], dict):
                m = metadata_obj[platform]
                # expected fields
                try:
                    slide_count_ok = (m.get("slide_count") == res["computed"].get("slide_count"))
                    cover_opts_ok = (m.get("cover_options") == res["computed"].get("cover_options"))
                    cta_opts_ok = (m.get("cta_options") == res["computed"].get("cta_options"))
                    caption_wc_ok = (m.get("caption_word_count") == res["computed"].get("caption_word_count"))
                    hb = m.get("hashtags_by_tier")
                    hbt_ok = (isinstance(hb, dict) and
                              hb.get("niche") == res["computed"].get("hashtags_by_tier", {}).get("niche") and
                              hb.get("mid") == res["computed"].get("hashtags_by_tier", {}).get("mid") and
                              hb.get("large") == res["computed"].get("hashtags_by_tier", {}).get("large"))
                    # headline max words equals requirement
                    headline_limit_req = reqs.get("headline_max_words", 8)
                    headline_max_ok = (m.get("headline_max_words") == headline_limit_req)
                    # banned words boolean
                    no_banned = m.get("no_banned_words")
                    no_banned_ok = (no_banned is True and res.get("banned_words_absent") is True)
                    ok_all = (slide_count_ok and cover_opts_ok and cta_opts_ok and caption_wc_ok and hbt_ok and headline_max_ok and no_banned_ok)
                    if platform == "linkedin":
                        metadata_matches_linkedin = ok_all
                    else:
                        metadata_matches_instagram = ok_all
                except Exception:
                    pass
    # Aggregate checks
    checks = {}
    # File existence checks
    checks["linkedin_file_exists"] = linkedin["file_exists"]
    checks["instagram_file_exists"] = instagram["file_exists"]
    checks["metadata_exists"] = os.path.isfile(metadata_path)
    # Structural/order
    checks["linkedin_structure_order"] = linkedin["order_ok"]
    checks["instagram_structure_order"] = instagram["order_ok"]
    # Slide counts
    checks["linkedin_slide_count"] = linkedin["slide_count_ok"]
    checks["instagram_slide_count"] = instagram["slide_count_ok"]
    # Slide fields
    checks["linkedin_slide_fields"] = linkedin["slides_fields_ok"]
    checks["instagram_slide_fields"] = instagram["slides_fields_ok"]
    # Headline length
    checks["linkedin_headline_lengths"] = linkedin["headline_lengths_ok"]
    checks["instagram_headline_lengths"] = instagram["headline_lengths_ok"]
    # Body lines
    checks["linkedin_body_lines"] = linkedin["body_lines_ok"]
    checks["instagram_body_lines"] = instagram["body_lines_ok"]
    # Transition hooks
    checks["linkedin_transition_hooks_ratio"] = linkedin["transition_hooks_ratio_ok"]
    checks["instagram_transition_hooks_ratio"] = instagram["transition_hooks_ratio_ok"]
    # Cover/CTA options
    checks["linkedin_cover_options"] = linkedin["cover_options_ok"]
    checks["linkedin_cta_options"] = linkedin["cta_options_ok"]
    checks["instagram_cover_options"] = instagram["cover_options_ok"]
    checks["instagram_cta_options"] = instagram["cta_options_ok"]
    # Caption range
    checks["linkedin_caption_range"] = linkedin["caption_range_ok"]
    checks["instagram_caption_range"] = instagram["caption_range_ok"]
    # Hashtag tiers
    checks["linkedin_hashtags_tiers"] = linkedin["hashtags_tiers_ok"]
    checks["instagram_hashtags_tiers"] = instagram["hashtags_tiers_ok"]
    # Dimensions string
    checks["linkedin_dimensions_string"] = linkedin["dimensions_string_ok"]
    checks["instagram_dimensions_string"] = instagram["dimensions_string_ok"]
    # Citation presence
    checks["linkedin_citation_present"] = linkedin["citation_present_ok"]
    checks["instagram_citation_present"] = instagram["citation_present_ok"]
    # Banned words
    checks["linkedin_banned_words_absent"] = linkedin["banned_words_absent"]
    checks["instagram_banned_words_absent"] = instagram["banned_words_absent"]
    # Metadata validation and matches
    checks["metadata_valid_json"] = metadata_valid_json
    checks["metadata_matches_linkedin"] = metadata_matches_linkedin
    checks["metadata_matches_instagram"] = metadata_matches_instagram
    # Compute reward as fraction of passed checks; baseline: if output dir missing or both md files missing, reward = 0.0
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Baseline guard
    if (not checks["linkedin_file_exists"] and not checks["instagram_file_exists"]) and not checks["metadata_exists"]:
        reward = 0.0
    else:
        reward = passed / total if total > 0 else 0.0
    # Print JSON result
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()