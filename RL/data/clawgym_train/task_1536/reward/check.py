import json
import os
import re
import sys
import hashlib

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.readlines()
    except Exception:
        return []

def normalize_header(line):
    s = line.strip()
    # remove leading markdown header markers
    while s.startswith("#"):
        s = s[1:].lstrip()
    return s

def find_section_ranges(lines, header_names):
    # header_names: list of canonical section titles as strings
    # returns dict: key lower(header) -> (start_index, end_index_exclusive)
    indices = []
    header_set_lower = {h.lower() for h in header_names}
    for i, line in enumerate(lines):
        norm = normalize_header(line)
        if norm.strip() == "":
            continue
        if norm.lower() in header_set_lower:
            # record canonical header as original-cased match from header_names
            # find the canonical form (case-insensitive match)
            canon = None
            for h in header_names:
                if norm.lower() == h.lower():
                    canon = h
                    break
            if canon is None:
                canon = norm
            indices.append((i, canon))
    ranges = {}
    for idx, (start, name) in enumerate(indices):
        end = len(lines)
        if idx + 1 < len(indices):
            end = indices[idx + 1][0]
        ranges[name.lower()] = (start + 1, end)  # content starts after header line
    return ranges

def count_lines_starting_with(lines, prefix):
    count = 0
    for ln in lines:
        if ln.lstrip().startswith(prefix):
            count += 1
    return count

def sha256_file(path):
    try:
        with open(path, "rb") as f:
            h = hashlib.sha256()
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def extract_company_name(investor_json):
    # Try common fields
    candidates = []
    for key in ["company_name", "company", "name", "companyName", "Company", "CompanyName"]:
        if isinstance(investor_json.get(key), str):
            candidates.append(investor_json.get(key))
    # Sometimes nested
    for key in ["company", "meta", "info", "details"]:
        if isinstance(investor_json.get(key), dict):
            for subkey in ["name", "company_name", "company", "display_name", "title"]:
                v = investor_json[key].get(subkey)
                if isinstance(v, str):
                    candidates.append(v)
    # Return the longest plausible name to avoid picking short tags
    candidates = [c.strip() for c in candidates if c and c.strip()]
    if not candidates:
        return None
    candidates.sort(key=lambda s: len(s), reverse=True)
    return candidates[0]

def split_tests_by_hypothesis(text):
    # Split content into blocks by 'Hypothesis:' markers (case-insensitive)
    # Keep the marker in blocks
    parts = re.split(r'(?i)(?=Hypothesis\s*:)', text)
    blocks = []
    for p in parts:
        if re.search(r'(?i)Hypothesis\s*:', p):
            blocks.append(p)
    return blocks

def contains_metric(text):
    metrics = [
        "ctr", "cvr", "conversion", "click rate", "click-rate", "click through", "click-through",
        "sign-ups", "signups", "signup rate", "form completion", "conversion rate", "submit rate"
    ]
    tl = text.lower()
    return any(m in tl for m in metrics)

def line_contains_microcopy(line):
    s = line.strip().lower()
    phrases = [
        "no credit card", "cancel anytime", "free for", "no questions asked",
        "setup takes", "risk-free", "money-back", "14 days", "trial", "guarantee"
    ]
    return any(p in s for p in phrases)

def find_sha256_line(text):
    # Return the first 64-hex digest found on a line starting with sha256:
    for line in text.splitlines():
        m = re.match(r'^\s*sha256:\s*([0-9a-fA-F]{64})\s*$', line.strip())
        if m:
            return m.group(1)
    return None

def has_required_labels(text, labels):
    lines = text.splitlines()
    found = {lbl: False for lbl in labels}
    for line in lines:
        low = line.strip().lower()
        for lbl in labels:
            if low.startswith(lbl + ":"):
                found[lbl] = True
    return all(found.values())

def detect_test_entries(text):
    # Count blocks with Hypothesis and a metric mention
    blocks = split_tests_by_hypothesis(text)
    count = 0
    for b in blocks:
        if contains_metric(b):
            count += 1
    return count

def count_scripts(lines):
    count = 0
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        if stripped.startswith('"'):
            count += 1
        elif stripped.startswith('- "') or stripped.startswith("- '"):
            count += 1
        elif re.match(r'(?i)^\s*script\s*:', ln):
            count += 1
        else:
            # pattern: a topic line ending with ":" and next line starts with a quote
            if stripped.endswith(":") and i + 1 < len(lines):
                nxt = lines[i + 1].lstrip()
                if nxt.startswith('"') or nxt.startswith("'"):
                    count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # landing page
        "landing_page_exists": False,
        "landing_page_has_sections": False,
        "hero_has_headline_subheadline_primary_cta_one": False,
        "benefits_has_three_bullets": False,
        "social_proof_has_two_testimonials": False,
        "cta_has_microcopy": False,
        # lead magnet
        "lead_magnet_exists": False,
        "lead_magnet_has_topics": False,
        "lead_magnet_has_three_scripts": False,
        # investor one pager
        "investor_one_pager_exists": False,
        "investor_has_company_name": False,
        "investor_has_raising_line": False,
        "investor_has_use_of_funds_section": False,
        "investor_has_disclaimer": False,
        # continuity
        "continuity_exists": False,
        "continuity_has_required_sections": False,
        "continuity_has_sha256_line": False,
        "continuity_hash_matches": False,
        # ab test
        "ab_test_plan_exists": False,
        "ab_test_has_three_tests": False,
        "ab_test_tests_have_metric": False,
    }

    # Paths
    landing_path = os.path.join(output_dir, "landing_page.md")
    lead_magnet_path = os.path.join(output_dir, "lead_magnet_scripts.md")
    investor_path = os.path.join(output_dir, "investor_one_pager.md")
    continuity_path = os.path.join(output_dir, "continuity_plan.md")
    ab_test_path = os.path.join(output_dir, "ab_test_plan.md")

    # 1) Landing page checks
    if os.path.isfile(landing_path):
        checks["landing_page_exists"] = True
        lines = read_lines(landing_path)
        headers = ["Hero", "Problem", "Solution", "Benefits", "Social Proof", "CTA"]
        section_ranges = find_section_ranges(lines, headers)
        has_all = all(h.lower() in section_ranges for h in [h.lower() for h in headers])
        checks["landing_page_has_sections"] = has_all

        if "hero" in section_ranges:
            start, end = section_ranges["hero"]
            hero_lines = lines[start:end]
            headline_count = count_lines_starting_with(hero_lines, "Headline:")
            subheadline_count = count_lines_starting_with(hero_lines, "Subheadline:")
            primary_cta_count = count_lines_starting_with(hero_lines, "Primary CTA:")
            if headline_count >= 1 and subheadline_count >= 1 and primary_cta_count == 1:
                checks["hero_has_headline_subheadline_primary_cta_one"] = True

        if "benefits" in section_ranges:
            start, end = section_ranges["benefits"]
            ben_lines = [ln.strip() for ln in lines[start:end]]
            bullets = [ln for ln in ben_lines if ln.startswith("-")]
            if len(bullets) >= 3:
                checks["benefits_has_three_bullets"] = True

        if "social proof" in section_ranges:
            start, end = section_ranges["social proof"]
            sp_lines = [ln.rstrip("\n") for ln in lines[start:end]]
            testimonial_count = 0
            for ln in sp_lines:
                # Line contains an em dash followed by a name (non-space sequence)
                if "—" in ln:
                    # ensure something after dash
                    if re.search(r'—\s*\S+', ln):
                        testimonial_count += 1
            if testimonial_count >= 2:
                checks["social_proof_has_two_testimonials"] = True

        if "cta" in section_ranges:
            start, end = section_ranges["cta"]
            cta_lines = [ln for ln in lines[start:end]]
            if any(line_contains_microcopy(ln) for ln in cta_lines):
                checks["cta_has_microcopy"] = True

    # 2) Lead magnet scripts checks
    if os.path.isfile(lead_magnet_path):
        checks["lead_magnet_exists"] = True
        lm_text = read_text(lead_magnet_path)
        tl = lm_text.lower()
        topics_ok = ("rent cap" in tl) and ("break clause" in tl) and ("deposit" in tl)
        checks["lead_magnet_has_topics"] = topics_ok

        lm_lines = read_lines(lead_magnet_path)
        script_count = count_scripts(lm_lines)
        if script_count >= 3:
            checks["lead_magnet_has_three_scripts"] = True

    # 3) Investor one-pager checks
    if os.path.isfile(investor_path):
        checks["investor_one_pager_exists"] = True
        inv_text = read_text(investor_path)
        # read investor_data.json for company name
        investor_data_path = os.path.join(input_dir, "investor_data.json")
        company_name = None
        if os.path.isfile(investor_data_path):
            try:
                with open(investor_data_path, "r", encoding="utf-8", errors="ignore") as f:
                    inv_json = json.load(f)
                company_name = extract_company_name(inv_json)
            except Exception:
                company_name = None
        if company_name:
            if company_name.lower() in inv_text.lower():
                checks["investor_has_company_name"] = True

        if re.search(r'(?i)Raising\s*\$', inv_text):
            checks["investor_has_raising_line"] = True

        if re.search(r'(?i)Use of Funds', inv_text):
            checks["investor_has_use_of_funds_section"] = True

        disclaimer = "This document is for informational purposes only and does not constitute an offer to sell or a solicitation of an offer to buy any securities."
        if disclaimer.lower() in inv_text.lower():
            checks["investor_has_disclaimer"] = True

    # 4) Continuity plan checks
    if os.path.isfile(continuity_path):
        checks["continuity_exists"] = True
        cont_text = read_text(continuity_path)
        required_labels = ["anchors", "risks", "verification_steps", "next_checkpoint"]
        if has_required_labels(cont_text, required_labels):
            checks["continuity_has_required_sections"] = True
        digest_in_file = find_sha256_line(cont_text)
        if digest_in_file is not None:
            checks["continuity_has_sha256_line"] = True
            # compute landing page sha256
            landing_digest = sha256_file(landing_path) if os.path.isfile(landing_path) else None
            if landing_digest is not None and landing_digest.lower() == digest_in_file.lower():
                checks["continuity_hash_matches"] = True

    # 5) A/B test plan checks
    if os.path.isfile(ab_test_path):
        checks["ab_test_plan_exists"] = True
        ab_text = read_text(ab_test_path)
        tests_with_metric = detect_test_entries(ab_text)
        if tests_with_metric >= 3:
            checks["ab_test_has_three_tests"] = True
            checks["ab_test_tests_have_metric"] = True

    # Compute reward: average of True checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # No-op baseline: if output dir missing or empty of required artifacts, ensure reward is 0.0
    required_files = [landing_path, lead_magnet_path, investor_path, continuity_path, ab_test_path]
    if not any(os.path.isfile(p) for p in required_files):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()