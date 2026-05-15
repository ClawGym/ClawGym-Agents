import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(path: Path):
    try:
        if path is None or not path.exists():
            return None
        text = _read_text_safe(path)
        if not text:
            return None
        return json.loads(text)
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _extract_block_after_key(lines, start_idx):
    key_line = lines[start_idx]
    indent = len(key_line) - len(key_line.lstrip(" "))
    block = []
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            block.append(line)
            continue
        current_indent = len(line) - len(line.lstrip(" "))
        if current_indent <= indent:
            break
        block.append(line)
    return block


def _parse_config_yaml(path: Path) -> dict:
    """
    Minimal parser tailored to provided YAML structure.
    Extracts only keys used for grading deterministically.
    """
    cfg_text = _read_text_safe(path)
    if not cfg_text:
        return {}

    lines = cfg_text.splitlines()

    def find_key_line_index(pattern: str):
        for idx, line in enumerate(lines):
            if re.match(pattern, line):
                return idx
        return -1

    cfg = {}

    # Simple scalar keys
    patterns = {
        "site_name": r'^\s*site_name:\s*"(.*)"\s*$',
        "drafts_dir": r'^\s*drafts_dir:\s*"(.*)"\s*$',
        "research_dir": r'^\s*research_dir:\s*"(.*)"\s*$',
        "nephew_name": r'^\s*nephew_name:\s*"(.*)"\s*$',
        "first_instrument": r'^\s*first_instrument:\s*"(.*)"\s*$',
        "first_introduced_song": r'^\s*first_introduced_song:\s*"(.*)"\s*$',
        "preferred_citation": r'^\s*preferred_citation:\s*"(.*)"\s*$',
        "min_sources": r'^\s*min_sources:\s*(\d+)\s*$',
    }
    for key, pat in patterns.items():
        m = re.search(pat, cfg_text, flags=re.M)
        if m:
            if key == "min_sources":
                try:
                    cfg[key] = int(m.group(1))
                except Exception:
                    pass
            else:
                cfg[key] = m.group(1)

    # author.display_name
    idx = find_key_line_index(r'^\s*author:\s*$')
    if idx != -1:
        block = _extract_block_after_key(lines, idx)
        for b in block:
            m = re.match(r'^\s*display_name:\s*"(.*)"\s*$', b)
            if m:
                cfg["author_display_name"] = m.group(1)
                break

    # default_tags: list under key
    tags = []
    idx = find_key_line_index(r'^\s*default_tags:\s*$')
    if idx != -1:
        block = _extract_block_after_key(lines, idx)
        for b in block:
            m = re.match(r'^\s*-\s*"(.*)"\s*$', b)
            if not m:
                m = re.match(r'^\s*-\s*(\S.*)\s*$', b)
            if m:
                tags.append(_strip_quotes(m.group(1)))
            else:
                if b.strip() and not b.strip().startswith("- "):
                    break
        if tags:
            cfg["default_tags"] = tags

    # front_matter.category
    idx = find_key_line_index(r'^\s*front_matter:\s*$')
    if idx != -1:
        block = _extract_block_after_key(lines, idx)
        for b in block:
            m = re.match(r'^\s*category:\s*"(.*)"\s*$', b)
            if not m:
                m = re.match(r'^\s*category:\s*(\S.*)\s*$', b)
            if m:
                cfg["front_matter_category"] = _strip_quotes(m.group(1))
                break

    # tone_guide: |
    idx = find_key_line_index(r'^\s*tone_guide:\s*\|\s*$')
    if idx != -1:
        block = _extract_block_after_key(lines, idx)
        guide_lines = []
        min_indent = None
        for b in block:
            if b.strip() == "" and not guide_lines:
                continue
            spaces = len(b) - len(b.lstrip(" "))
            if min_indent is None and b.strip():
                min_indent = spaces
            if min_indent is None:
                min_indent = 0
            if spaces >= min_indent:
                guide_lines.append(b[min_indent:])
            else:
                guide_lines.append(b)
        cfg["tone_guide"] = "\n".join([l.rstrip("\n") for l in guide_lines]).strip()

    return cfg


def _parse_front_matter_and_body(md_text: str):
    """
    Parse YAML-like front matter: entries of form
    ---
    key: value
    list:
      - item
    ---
    body...
    Returns (front_matter_dict, body_text)
    """
    if not md_text.startswith("---"):
        return None, md_text
    parts = md_text.split("\n")
    if len(parts) < 3:
        return None, md_text
    # Find closing '---'
    end_idx = -1
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            end_idx = i
            break
    if end_idx == -1:
        return None, md_text
    fm_lines = parts[1:end_idx]
    body = "\n".join(parts[end_idx + 1 :])

    fm = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if not line.strip():
            i += 1
            continue
        if re.match(r'^\s*tags:\s*$', line):
            i += 1
            tags = []
            while i < len(fm_lines):
                l2 = fm_lines[i]
                if re.match(r'^\s*-\s+', l2):
                    item = re.sub(r'^\s*-\s+', '', l2).strip()
                    item = _strip_quotes(item)
                    tags.append(item)
                    i += 1
                    continue
                elif not l2.strip():
                    i += 1
                    continue
                else:
                    break
            fm["tags"] = tags
            continue
        m = re.match(r'^\s*([A-Za-z0-9_]+):\s*(.*)\s*$', line)
        if m:
            key = m.group(1)
            val = m.group(2)
            val = _strip_quotes(val)
            if re.fullmatch(r'-?\d+', val):
                try:
                    fm[key] = int(val)
                except Exception:
                    fm[key] = val
            else:
                fm[key] = val
        i += 1

    return fm, body


def _extract_section(body: str, heading: str) -> str:
    """
    Extract content under a second-level heading '## heading'
    """
    lines = body.splitlines()
    content_lines = []
    in_section = False
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## ") and line.strip()[3:].strip().lower() == heading.lower():
            in_section = True
            continue
        if in_section:
            if line.strip().startswith("## "):
                break
            content_lines.append(line)
    return "\n".join(content_lines).strip()


def _find_bullet_lines(text: str) -> list:
    bullets = []
    for line in text.splitlines():
        if re.match(r'^\s*-\s+', line):
            bullets.append(re.sub(r'^\s*-\s+', '', line).strip())
    return bullets


def _count_sentences(text: str) -> int:
    parts = re.split(r'[.!?]+', text)
    count = sum(1 for p in parts if p.strip())
    return count


def _domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        host = host.split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _all_required_config_keys(cfg: dict) -> bool:
    required = [
        "site_name",
        "author_display_name",
        "drafts_dir",
        "research_dir",
        "default_tags",
        "nephew_name",
        "first_instrument",
        "first_introduced_song",
        "front_matter_category",
        "min_sources",
    ]
    for k in required:
        if k not in cfg or cfg[k] in (None, "", []):
            return False
    if not isinstance(cfg.get("default_tags"), list):
        return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_parse_success": 0.0,
        "research_json_valid_structure": 0.0,
        "research_min_sources_and_coverage": 0.0,
        "research_notes_briefness": 0.0,
        "research_url_domain_consistency": 0.0,
        "blog_file_path_correct": 0.0,
        "title_author_category_correct": 0.0,
        "tags_include_defaults_and_letter": 0.0,
        "fact_check_source_count_matches": 0.0,
        "body_sections_present": 0.0,
        "how_it_started_mentions_song_and_instrument": 0.0,
        "listening_guide_three_bullets": 0.0,
        "listening_guide_content_keywords": 0.0,
        "listening_guide_blurb_lengths": 0.0,
        "sources_consulted_matches_research": 0.0,
        "no_urls_in_post_body": 0.0,
    }

    # Load config
    config_path = workspace / "config" / "site_config.yaml"
    cfg = _parse_config_yaml(config_path)

    # Determine expected paths strictly from config (no hardcoded fallbacks)
    drafts_dir = cfg.get("drafts_dir")
    research_dir = cfg.get("research_dir")
    nephew_name = cfg.get("nephew_name")

    # Research JSON
    sources_path = None
    if isinstance(research_dir, str) and research_dir:
        sources_path = workspace / research_dir / "sources.json"

    sources = _load_json_safe(sources_path) if sources_path else None
    research_valid = False
    research_entries = []
    if isinstance(sources, list):
        # Validate each entry has required keys and non-empty strings
        required_fields = ["query", "source_title", "source_domain", "url", "notes", "used_for"]
        all_ok = True
        for entry in sources:
            if not isinstance(entry, dict):
                all_ok = False
                break
            for f in required_fields:
                v = entry.get(f)
                if not isinstance(v, str) or not v.strip():
                    all_ok = False
                    break
            if not all_ok:
                break
            if entry.get("used_for") not in ("song_history", "concept_explainer"):
                all_ok = False
                break
            research_entries.append(entry)
        if all_ok:
            research_valid = True

    if research_valid:
        scores["research_json_valid_structure"] = 1.0

    # min_sources and coverage of used_for categories
    min_sources = cfg.get("min_sources") if isinstance(cfg.get("min_sources"), int) else None
    if research_valid and isinstance(min_sources, int):
        count_ok = len(research_entries) >= min_sources
        coverage_ok = any(e.get("used_for") == "song_history" for e in research_entries) and any(
            e.get("used_for") == "concept_explainer" for e in research_entries
        )
        if count_ok and coverage_ok:
            scores["research_min_sources_and_coverage"] = 1.0

    # notes briefness: 1-2 sentences
    if research_valid:
        nb_ok = True
        for e in research_entries:
            n = e.get("notes", "")
            sent = _count_sentences(n)
            if sent < 1 or sent > 2:
                nb_ok = False
                break
        if nb_ok:
            scores["research_notes_briefness"] = 1.0

    # URL and domain consistency
    if research_valid:
        ud_ok = True
        for e in research_entries:
            url = e.get("url", "")
            sd = e.get("source_domain", "").lower().lstrip().rstrip()
            url_dom = _domain_from_url(url)
            if url_dom != sd and not (url_dom.endswith("." + sd) or sd.endswith("." + url_dom)):
                ud_ok = False
                break
        if ud_ok:
            scores["research_url_domain_consistency"] = 1.0

    # Blog file
    blog_path = None
    if isinstance(drafts_dir, str) and drafts_dir and isinstance(nephew_name, str) and nephew_name:
        blog_filename = f"a-letter-to-{nephew_name}-about-the-music.md"
        blog_path = workspace / drafts_dir / blog_filename

    blog_text = _read_text_safe(blog_path) if blog_path else ""
    if blog_text:
        scores["blog_file_path_correct"] = 1.0

    # Front matter and body
    fm, body = _parse_front_matter_and_body(blog_text) if blog_text else (None, "")
    title_ok = False
    author_ok = False
    category_ok = False
    tags_ok = False
    fact_count_ok = False

    if isinstance(fm, dict) and _all_required_config_keys(cfg):
        expected_title = f'{cfg["site_name"]}: A Letter to {cfg["nephew_name"]}'
        title_ok = fm.get("title") == expected_title
        author_ok = fm.get("author") == cfg["author_display_name"]
        category_ok = fm.get("category") == cfg["front_matter_category"]
        # tags include defaults + "letter"
        tags_val = fm.get("tags")
        if isinstance(tags_val, list):
            needed = set(cfg["default_tags"] + ["letter"])
            tags_ok = needed.issubset(set(tags_val))
        # fact_check_source_count equals number of research entries
        if research_valid:
            try:
                fact_count_ok = int(fm.get("fact_check_source_count")) == len(research_entries)
            except Exception:
                fact_count_ok = False

    if title_ok and author_ok and category_ok:
        scores["title_author_category_correct"] = 1.0

    if tags_ok:
        scores["tags_include_defaults_and_letter"] = 1.0

    if fact_count_ok:
        scores["fact_check_source_count_matches"] = 1.0

    # Body sections presence
    how_text = _extract_section(body, "How it started") if body else ""
    listen_text = _extract_section(body, "Listening guide") if body else ""
    sources_text = _extract_section(body, "Sources consulted") if body else ""
    if how_text and listen_text and sources_text:
        scores["body_sections_present"] = 1.0

    # How it started mentions song and instrument
    if how_text and cfg.get("first_introduced_song") and cfg.get("first_instrument"):
        s_ok = cfg["first_introduced_song"].lower() in how_text.lower()
        i_ok = cfg["first_instrument"].lower() in how_text.lower()
        if s_ok and i_ok:
            scores["how_it_started_mentions_song_and_instrument"] = 1.0

    # Listening guide bullets - exactly three bullets and specific content per bullet
    listen_bullets = _find_bullet_lines(listen_text) if listen_text else []
    if len(listen_bullets) == 3:
        scores["listening_guide_three_bullets"] = 1.0

        lb_lower = [b.lower() for b in listen_bullets]
        song_name = (cfg.get("first_introduced_song") or "").lower()

        # Bullet 1: performance/recording of the introduced song to revisit
        b1_ok = ("performance" in lb_lower[0] or "recording" in lb_lower[0] or (song_name and song_name in lb_lower[0]))
        # Bullet 2: classic album
        b2_ok = ("album" in lb_lower[1] or "record" in lb_lower[1])
        # Bullet 3: modern artist to explore
        b3_ok = ("artist" in lb_lower[2] or "modern" in lb_lower[2] or "contemporary" in lb_lower[2])

        if b1_ok and b2_ok and b3_ok:
            scores["listening_guide_content_keywords"] = 1.0

        # Blurb lengths 1-2 sentences for each bullet
        bl_ok = True
        for b in listen_bullets:
            sc = _count_sentences(b)
            if sc < 1 or sc > 2:
                bl_ok = False
                break
        if bl_ok:
            scores["listening_guide_blurb_lengths"] = 1.0

    # Sources consulted matches research: list each source_domain and source_title as bullet points
    if sources_text and research_valid:
        bullets = _find_bullet_lines(sources_text)
        all_present = True
        for e in research_entries:
            dom = e.get("source_domain", "").strip()
            title = e.get("source_title", "").strip()
            found = any((dom in b and title in b) for b in bullets)
            if not found:
                all_present = False
                break
        count_match = len(bullets) == len(research_entries)
        if all_present and count_match:
            scores["sources_consulted_matches_research"] = 1.0

    # No URLs in post body
    if body:
        if ("http://" not in body) and ("https://" not in body) and ("www." not in body):
            scores["no_urls_in_post_body"] = 1.0

    # Award config_parse_success only when config is present and both deliverables appear validly
    if _all_required_config_keys(cfg) and blog_text and research_valid:
        scores["config_parse_success"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()