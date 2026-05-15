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

def split_lines(text):
    return text.splitlines()

def count_bullets(lines):
    return sum(1 for ln in lines if ln.strip().startswith("- "))

def extract_section(lines, start_idx):
    # Given index of a section header line ("### ..."), return content lines until next "### " or EOF
    content = []
    i = start_idx + 1
    while i < len(lines):
        if lines[i].strip().startswith("### "):
            break
        content.append(lines[i])
        i += 1
    return content

def parse_digest(digest_text):
    result = {
        "header_ok": False,
        "sections_order_ok": False,
        "counts_match": False,
        "must_listen_has_2": False,
        "must_listen_slugs_ok": False,
        "must_listen_slugs": [],
    }
    lines = split_lines(digest_text)
    # Find first non-empty line
    first_non_empty = None
    for ln in lines:
        if ln.strip():
            first_non_empty = ln
            break
    if first_non_empty and first_non_empty.strip().startswith("## ") and "This Week in Podcasts" in first_non_empty:
        result["header_ok"] = True

    # Find section headings and indices
    sec_patterns = [
        ("Must Listen", re.compile(r"^###\s+Must Listen\s*\((\d+)\)\s*$")),
        ("Worth Skimming", re.compile(r"^###\s+Worth Skimming\s*\((\d+)\)\s*$")),
        ("Safe to Skip", re.compile(r"^###\s+Safe to Skip\s*\((\d+)\)\s*$")),
    ]
    found = []
    for idx, ln in enumerate(lines):
        for name, pat in sec_patterns:
            m = pat.match(ln.strip())
            if m:
                found.append((name, idx, int(m.group(1))))
                break

    # Verify order and presence of all three in correct order
    if len(found) >= 3:
        names_in_order = [f[0] for f in found]
        # Build mapping of first occurrences
        order_required = ["Must Listen", "Worth Skimming", "Safe to Skip"]
        # Extract the first occurrence indices for each required section in order
        positions = []
        remaining = found[:]
        ok_order = True
        last_pos = -1
        matched_sections = []
        for req in order_required:
            pos = None
            for name, idx, cnt in remaining:
                if name == req:
                    pos = idx
                    matched_sections.append((name, idx, cnt))
                    break
            if pos is None or pos <= last_pos:
                ok_order = False
                break
            last_pos = pos
        if ok_order and len(matched_sections) == 3:
            result["sections_order_ok"] = True
            # Now count bullets within each section and compare counts; also collect Must Listen bullets
            counts_match = True
            must_listen_bullets = []
            for i, (name, idx, declared) in enumerate(matched_sections):
                # Determine content range: from this idx to next section heading or EOF
                content = extract_section(lines, idx)
                # Count lines starting with "- "
                bullet_count = sum(1 for ln in content if ln.strip().startswith("- "))
                if bullet_count != declared:
                    counts_match = False
                if name == "Must Listen":
                    must_listen_bullets = [ln for ln in content if ln.strip().startswith("- ")]
            result["counts_match"] = counts_match
            # Must Listen count must be exactly 2
            if len(must_listen_bullets) == 2:
                result["must_listen_has_2"] = True
            # For each Must Listen bullet, verify slug pattern ending and collect slugs
            slugs = []
            slug_ok = True
            slug_re = re.compile(r"\(slug:\s*([a-z0-9-]+)\)\s*$")
            for ln in must_listen_bullets:
                m = slug_re.search(ln.strip())
                if not m:
                    slug_ok = False
                    break
                slug = m.group(1)
                # Ensure the bullet line ends with the slug token
                if not ln.strip().endswith(f"(slug: {slug})"):
                    slug_ok = False
                    break
                # Valid slug format already via regex
                slugs.append(slug)
            if slug_ok and len(slugs) == 2:
                result["must_listen_slugs_ok"] = True
                result["must_listen_slugs"] = slugs
    return result

def parse_briefing(brief_text):
    lines = split_lines(brief_text)
    # First line starts with "## "
    first_line_ok = False
    if lines:
        if lines[0].lstrip().startswith("## "):
            first_line_ok = True
    guest_line_ok = any(ln.strip().startswith("Guest:") for ln in lines)

    # Find indices of section headers
    headers = {
        "TL;DR": None,
        "Key Points": None,
        "Quotable Moments": None,
        "Action Items": None,
        "Skip or Listen?": None,
    }
    header_indices = {}
    for idx, ln in enumerate(lines):
        s = ln.strip()
        for key in headers:
            if s == f"### {key}":
                header_indices[key] = idx
    has_all_headers = all(k in header_indices for k in headers)
    # Extract sections content
    sects = {}
    if has_all_headers:
        # Need order by position; easier: for each, use extract_section with current index
        for k, idx in header_indices.items():
            sects[k] = extract_section(lines, idx)
    # TL;DR: 2–3 sentences minimum 2
    tldr_ok = False
    if has_all_headers:
        tldr_text = "\n".join(sects.get("TL;DR", []))
        # Count sentences by ., !, ? delimiters
        # Replace newlines with space to avoid empty sentences
        condensed = re.sub(r"\s+", " ", tldr_text).strip()
        # Count by splitting on end punctuation followed by space or end
        # Use regex to find sentence enders
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", condensed) if s.strip()]
        if len(sentences) >= 2:
            tldr_ok = True
    # Key Points: at least 3 bullet lines starting with "- "
    keypoints_ok = False
    if has_all_headers:
        kp_lines = sects.get("Key Points", [])
        kp_count = sum(1 for ln in kp_lines if ln.strip().startswith("- "))
        if kp_count >= 3:
            keypoints_ok = True
    # Quotable Moments: at least 1 blockquote line starting with ">"
    quotable_ok = False
    if has_all_headers:
        q_lines = sects.get("Quotable Moments", [])
        if any(ln.strip().startswith(">") for ln in q_lines):
            quotable_ok = True
    # Action Items: at least 1 checkbox line starting with "- [ ]"
    action_ok = False
    if has_all_headers:
        a_lines = sects.get("Action Items", [])
        if any(ln.strip().startswith("- [ ]") for ln in a_lines):
            action_ok = True
    # Skip or Listen?: includes one of [MUST LISTEN], [WORTH IT], [SKIP]
    sol_ok = False
    if has_all_headers:
        s_lines = sects.get("Skip or Listen?", [])
        joined = "\n".join(s_lines)
        if any(tag in joined for tag in ["[MUST LISTEN]", "[WORTH IT]", "[SKIP]"]):
            sol_ok = True

    return {
        "first_line_ok": first_line_ok,
        "guest_line_ok": guest_line_ok,
        "has_all_headers": has_all_headers,
        "tldr_ok": tldr_ok,
        "keypoints_ok": keypoints_ok,
        "quotable_ok": quotable_ok,
        "action_ok": action_ok,
        "skip_or_listen_ok": sol_ok,
    }

def compute_guest_mentions(guest_entries, digest_text, briefing_texts):
    # guest_entries: list of dicts with name, mentions (expected)
    # Count occurrences of each name across digest + briefings (case-insensitive)
    content = (digest_text or "") + "\n" + "\n".join(bt or "" for bt in briefing_texts)
    results = {}
    for entry in guest_entries:
        name = entry.get("name", "")
        if not isinstance(name, str):
            results[name] = None
            continue
        pattern = re.escape(name)
        count = len(re.findall(pattern, content, flags=re.IGNORECASE))
        results[name] = count
    return results

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "digest_exists": False,
        "digest_header_ok": False,
        "digest_sections_order_ok": False,
        "digest_section_counts_match": False,
        "must_listen_has_2": False,
        "must_listen_slugs_ok": False,
        "briefings_exist": False,
        "briefing_structure_all_ok": False,
        "tldr_sentences_ok": False,
        "keypoints_count_ok": False,
        "quotable_line_ok": False,
        "action_items_ok": False,
        "skip_or_listen_label_ok": False,
        "queue_exists": False,
        "queue_first_line_ok": False,
        "queue_first_two_cover_slugs": False,
        "guests_summary_exists": False,
        "guests_summary_valid_schema": False,
        "guests_summary_mentions_match": False,
    }

    digest_path = os.path.join(output_dir, "digest.md")
    digest_text = read_text(digest_path)
    must_slugs = []
    if digest_text is not None:
        checks["digest_exists"] = True
        digest_parsed = parse_digest(digest_text)
        checks["digest_header_ok"] = digest_parsed["header_ok"]
        checks["digest_sections_order_ok"] = digest_parsed["sections_order_ok"]
        checks["digest_section_counts_match"] = digest_parsed["counts_match"]
        checks["must_listen_has_2"] = digest_parsed["must_listen_has_2"]
        checks["must_listen_slugs_ok"] = digest_parsed["must_listen_slugs_ok"]
        must_slugs = digest_parsed["must_listen_slugs"] if digest_parsed["must_listen_slugs_ok"] else []
    else:
        must_slugs = []

    # Briefings checks
    briefing_texts = []
    if must_slugs and len(must_slugs) == 2:
        briefing_paths = [os.path.join(output_dir, "briefings", f"{slug}.md") for slug in must_slugs]
        if all(os.path.isfile(p) for p in briefing_paths):
            checks["briefings_exist"] = True
            all_struct_ok = True
            all_tldr_ok = True
            all_kp_ok = True
            all_q_ok = True
            all_act_ok = True
            all_sol_ok = True
            for p in briefing_paths:
                bt = read_text(p)
                briefing_texts.append(bt or "")
                if bt is None:
                    all_struct_ok = False
                    all_tldr_ok = False
                    all_kp_ok = False
                    all_q_ok = False
                    all_act_ok = False
                    all_sol_ok = False
                    continue
                parsed = parse_briefing(bt)
                struct_ok = parsed["first_line_ok"] and parsed["guest_line_ok"] and parsed["has_all_headers"]
                all_struct_ok = all_struct_ok and struct_ok
                all_tldr_ok = all_tldr_ok and parsed["tldr_ok"]
                all_kp_ok = all_kp_ok and parsed["keypoints_ok"]
                all_q_ok = all_q_ok and parsed["quotable_ok"]
                all_act_ok = all_act_ok and parsed["action_ok"]
                all_sol_ok = all_sol_ok and parsed["skip_or_listen_ok"]
            checks["briefing_structure_all_ok"] = all_struct_ok
            checks["tldr_sentences_ok"] = all_tldr_ok
            checks["keypoints_count_ok"] = all_kp_ok
            checks["quotable_line_ok"] = all_q_ok
            checks["action_items_ok"] = all_act_ok
            checks["skip_or_listen_label_ok"] = all_sol_ok

    # Queue checks
    queue_path = os.path.join(output_dir, "queue_prioritized.md")
    queue_text = read_text(queue_path)
    if queue_text is not None:
        checks["queue_exists"] = True
        q_lines = split_lines(queue_text)
        if q_lines and q_lines[0].strip() == "Time Budget: 3h":
            checks["queue_first_line_ok"] = True
        # Identify first two numbered list items starting with "1." and "2."
        first_num_line = None
        second_num_line = None
        for ln in q_lines[1:]:
            s = ln.strip()
            if first_num_line is None and s.startswith("1."):
                first_num_line = s
            elif second_num_line is None and s.startswith("2."):
                second_num_line = s
            if first_num_line and second_num_line:
                break
        if first_num_line and second_num_line and must_slugs and len(must_slugs) == 2:
            # Extract slugs in "(slug: <slug>)" format
            slug_pat = re.compile(r"\(slug:\s*([a-z0-9-]+)\)")
            m1 = slug_pat.search(first_num_line)
            m2 = slug_pat.search(second_num_line)
            if m1 and m2:
                s1 = m1.group(1)
                s2 = m2.group(1)
                if set([s1, s2]) == set(must_slugs):
                    checks["queue_first_two_cover_slugs"] = True

    # Guests summary checks
    guests_summary_path = os.path.join(output_dir, "guests", "summary.json")
    guests_summary_text = read_text(guests_summary_path)
    guest_entries = None
    if guests_summary_text is not None:
        checks["guests_summary_exists"] = True
        try:
            parsed = json.loads(guests_summary_text)
            if isinstance(parsed, list) and len(parsed) >= 2 and all(isinstance(el, dict) for el in parsed):
                schema_ok = True
                for el in parsed:
                    if not isinstance(el.get("name"), str):
                        schema_ok = False
                        break
                    if not isinstance(el.get("mentions"), int):
                        schema_ok = False
                        break
                if schema_ok:
                    checks["guests_summary_valid_schema"] = True
                    guest_entries = parsed
        except Exception:
            pass

    if checks["guests_summary_valid_schema"] and guest_entries is not None and checks["digest_exists"] and checks["briefings_exist"]:
        # Compute mentions across digest and the two briefing files
        mentions_calc = compute_guest_mentions(guest_entries, digest_text or "", briefing_texts)
        match_all = True
        for el in guest_entries:
            name = el["name"]
            expected = el["mentions"]
            actual = mentions_calc.get(name)
            if actual is None or actual != expected:
                match_all = False
                break
        checks["guests_summary_mentions_match"] = match_all

    # Compute reward as fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    # No-op baseline: if output missing or key artifacts missing, ensure reward is 0.0
    # This is already handled by checks being False.
    if total > 0:
        reward = passed / total
    # Clamp between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object on last non-empty line
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()