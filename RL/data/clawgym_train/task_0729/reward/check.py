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

def normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")

def parse_requests_yaml(yaml_text: str):
    title = None
    include = []
    if yaml_text is None:
        return title, include
    text = normalize_newlines(yaml_text)
    lines = text.split("\n")
    # simple parse for title
    for ln in lines:
        ls = ln.strip()
        if ls.startswith("title:"):
            val = ls.split(":", 1)[1].strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            title = val
            break
    # parse include
    in_list = False
    for i, ln in enumerate(lines):
        if not in_list:
            if re.match(r"^\s*include\s*:\s*(\[.*\])\s*$", ln):
                # bracket list
                m = re.match(r"^\s*include\s*:\s*\[(.*)\]\s*$", ln)
                if m:
                    body = m.group(1).strip()
                    if body:
                        parts = [p.strip() for p in body.split(",")]
                        for p in parts:
                            if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                                p = p[1:-1]
                            if p:
                                include.append(p)
                break
            elif re.match(r"^\s*include\s*:\s*$", ln):
                in_list = True
                continue
        else:
            if re.match(r"^\s*-\s+", ln):
                item = re.sub(r"^\s*-\s+", "", ln).strip()
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                if item:
                    include.append(item)
            else:
                # end of list
                in_list = False
    return title, include

def slug_to_title(slug: str) -> str:
    mapping = {
        "intro": "Intro",
        "quickstart": "Quickstart",
        "patterns": "Patterns",
        "debugging": "Debugging",
        "performance": "Performance",
        "security": "Security",
        "team_notes": "Team Notes",
    }
    return mapping.get(slug, slug.title())

def find_section_range(text: str, header_label: str):
    # returns (start_idx_of_content_after_header_line, end_idx_before_next_header)
    pattern = re.compile(r'^\s*##\s+' + re.escape(header_label) + r'\s*$', re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return None
    # move to after the end of the header line
    end_of_header_line = text.find("\n", m.end())
    if end_of_header_line == -1:
        section_start = len(text)
    else:
        section_start = end_of_header_line + 1
    # find next "## " header
    next_hdr = re.compile(r'^\s*##\s+', re.MULTILINE).search(text, section_start)
    if not next_hdr:
        section_end = len(text)
    else:
        section_end = next_hdr.start()
    return (section_start, section_end)

def count_bullets(section_text: str) -> int:
    count = 0
    for line in section_text.splitlines():
        if re.match(r'^\s*[-*]\s+', line):
            count += 1
    return count

def words_between(text: str, start_idx: int, end_idx: int) -> int:
    seg = text[start_idx:end_idx]
    # count words as sequences of alphanumerics/underscore
    return len(re.findall(r'\b\w+\b', seg))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # guide file checks
        "guide_exists": False,
        "title_matches": False,
        "has_contents": False,
        "contents_order": False,
        "exec_summary_length": False,
        "section_intro_header": False,
        "section_intro_canonical": False,
        "section_quickstart_header": False,
        "section_quickstart_canonical": False,
        "section_patterns_header": False,
        "section_patterns_canonical": False,
        "section_debugging_header": False,
        "section_debugging_canonical": False,
        "section_performance_header": False,
        "section_performance_canonical": False,
        "section_security_header": False,
        "section_security_canonical": False,
        "has_team_notes": False,
        "team_notes_verbatim": False,
        "has_next_steps": False,
        "next_steps_bullets_ge3": False,

        # index file checks
        "index_exists": False,
        "index_json_valid": False,
        "index_title_match": False,
        "index_requested_sections_match": False,
        "index_sections_match": False,
        "index_total_sections_match": False,
        "index_toc_present_true": False,
    }

    # Read inputs
    requests_yaml_path = os.path.join(input_dir, "requests.yaml")
    team_notes_path = os.path.join(input_dir, "team_notes.md")
    requests_yaml = read_text(requests_yaml_path)
    team_notes = read_text(team_notes_path)
    if team_notes is None:
        team_notes = ""  # still used only for comparison when output exists
    team_notes_norm = normalize_newlines(team_notes)

    title, include = parse_requests_yaml(requests_yaml if requests_yaml is not None else "")

    # Expected canonical substrings for sections (must be present in the section content)
    canonical_subs = {
        "intro": ["Moodring — Overview", "What is Moodring?"],
        "quickstart": ["Moodring — Quick Start Guide", "## Prerequisites"],
        "patterns": ["Moodring — Common Patterns & Best Practices", "## Best Practices"],
        "debugging": ["Moodring — Debugging Guide", "## Debug Workflow"],
        "performance": ["Moodring — Performance Optimization", "## Key Metrics"],
        "security": ["Moodring — Security Considerations", "## Data Protection"],
    }

    # Check moodring_guide.md
    guide_path = os.path.join(output_dir, "moodring_guide.md")
    guide_text = read_text(guide_path)
    if guide_text is not None:
        checks["guide_exists"] = True
        guide_text = normalize_newlines(guide_text)

        # Title H1 exact match to requests.yaml.title
        if title is not None:
            # find a line that is exactly "# {title}"
            title_pattern = re.compile(r'^\s*#\s+' + re.escape(title) + r'\s*$', re.MULTILINE)
            m_title = title_pattern.search(guide_text)
            if m_title:
                checks["title_matches"] = True

        # Find "## Contents"
        contents_range = find_section_range(guide_text, "Contents")
        if contents_range is not None:
            checks["has_contents"] = True

        # Exec summary length between H1 (title) and "## Contents"
        if contents_range is not None and title is not None:
            # locate the matching H1 line for this title
            h1_pattern = re.compile(r'^\s*#\s+' + re.escape(title) + r'\s*$', re.MULTILINE)
            m_h1 = h1_pattern.search(guide_text)
            if m_h1:
                # Determine start after the title line
                end_of_h1_line = guide_text.find("\n", m_h1.end())
                summary_start = end_of_h1_line + 1 if end_of_h1_line != -1 else len(guide_text)
                summary_end = contents_range[0]
                if summary_end >= summary_start:
                    wc = words_between(guide_text, summary_start, summary_end)
                    if 80 <= wc <= 120:
                        checks["exec_summary_length"] = True

        # Contents order check: ensure listed sections appear in exact order
        if contents_range is not None and include:
            contents_text = guide_text[contents_range[0]:contents_range[1]]
            # We check that each TitleCase name appears in order
            pos = 0
            ok = True
            for slug in include:
                name = slug_to_title(slug)
                idx = contents_text.find(name, pos)
                if idx == -1:
                    ok = False
                    break
                pos = idx + 1
            if ok:
                checks["contents_order"] = True

        # For each included slug, check header and canonical content within the section
        for slug in include:
            titlecase = slug_to_title(slug)
            header_key = f"section_{slug}_header"
            canon_key = f"section_{slug}_canonical"
            if header_key not in checks:
                # ensure a key exists even if unexpected slug; create dynamically but keep False by default
                checks[header_key] = False
            if canon_key not in checks:
                checks[canon_key] = False

            sec_range = find_section_range(guide_text, titlecase)
            if sec_range is not None:
                checks[header_key] = True
                sec_text = guide_text[sec_range[0]:sec_range[1]]
                if slug in canonical_subs:
                    needed = canonical_subs[slug]
                    if all(sub in sec_text for sub in needed):
                        checks[canon_key] = True

        # Team Notes section presence and verbatim embedding
        tn_range = find_section_range(guide_text, "Team Notes")
        if tn_range is not None:
            checks["has_team_notes"] = True
            tn_text = normalize_newlines(guide_text[tn_range[0]:tn_range[1]])
            # Check verbatim substring
            if team_notes_norm and team_notes_norm in tn_text:
                checks["team_notes_verbatim"] = True
            else:
                # also try stripped variant to be slightly tolerant of trailing newline differences
                if team_notes_norm.strip() and team_notes_norm.strip() in tn_text:
                    checks["team_notes_verbatim"] = True

        # Next Steps section and bullet count
        ns_range = find_section_range(guide_text, "Next Steps")
        if ns_range is not None:
            checks["has_next_steps"] = True
            ns_text = guide_text[ns_range[0]:ns_range[1]]
            if count_bullets(ns_text) >= 3:
                checks["next_steps_bullets_ge3"] = True

    # Check index.json
    index_path = os.path.join(output_dir, "index.json")
    index_text = read_text(index_path)
    if index_text is not None:
        checks["index_exists"] = True
        try:
            idx_obj = json.loads(index_text)
            checks["index_json_valid"] = True

            # title
            if title is not None and isinstance(idx_obj.get("title"), str) and idx_obj.get("title") == title:
                checks["index_title_match"] = True

            # requested_sections
            if isinstance(idx_obj.get("requested_sections"), list) and idx_obj.get("requested_sections") == include:
                checks["index_requested_sections_match"] = True

            # sections = include + ["team_notes"]
            expected_sections = list(include) + ["team_notes"]
            if isinstance(idx_obj.get("sections"), list) and idx_obj.get("sections") == expected_sections:
                checks["index_sections_match"] = True

            # total_sections
            if isinstance(idx_obj.get("total_sections"), int) and idx_obj.get("total_sections") == len(expected_sections):
                checks["index_total_sections_match"] = True

            # toc_present true
            if idx_obj.get("toc_present") is True:
                checks["index_toc_present_true"] = True

        except Exception:
            # keep defaults false
            pass

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v is True)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # No-op baseline: if no artifacts exist or none passed, keep 0.0
    if passed_checks == 0:
        reward = 0.0

    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()