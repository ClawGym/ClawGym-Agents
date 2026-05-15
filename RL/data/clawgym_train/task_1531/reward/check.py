import json
import os
import re
import sys
from datetime import date

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def list_md_files(root_dir):
    files = []
    for base, dirs, filenames in os.walk(root_dir):
        for fn in filenames:
            if fn.lower().endswith(".md"):
                files.append(os.path.join(base, fn))
    return files

def starts_with_frontmatter(text):
    if text is None:
        return False, None, None
    # Must begin at the very start
    if not text.startswith("---"):
        return False, None, None
    lines = text.splitlines()
    if len(lines) == 0 or lines[0].strip() != "---":
        return False, None, None
    # Find closing '---'
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return False, None, None
    front_lines = lines[1:end_idx]
    front_text = "\n".join(front_lines)
    content_after = "\n".join(lines[end_idx+1:])
    return True, front_text, content_after

def parse_tags_from_front(front_text):
    tags = None
    for line in front_text.splitlines():
        # capture tags line
        m = re.match(r"^\s*tags\s*:\s*(.+)\s*$", line)
        if m:
            val = m.group(1).strip()
            # YAML array like [tag1, tag2]
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1]
                parts = [p.strip().strip("'").strip('"') for p in inner.split(",")]
                tags = [p for p in parts if p]
            else:
                # single or comma-separated string
                parts = [p.strip().strip("'").strip('"') for p in val.split(",")]
                tags = [p for p in parts if p]
            break
    return tags

def parse_created_from_front(front_text):
    created = None
    for line in front_text.splitlines():
        m = re.match(r"^\s*created\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", line)
        if m:
            created = m.group(1)
            break
    return created

def has_level1_heading(content_text):
    if content_text is None:
        return False
    for line in content_text.splitlines():
        if line.startswith("# "):
            return True
    return False

def has_confidence_levels_heading(full_text):
    if full_text is None:
        return False
    for line in full_text.splitlines():
        if line.strip() == "## Confidence levels":
            return True
    return False

def normalize_tags_list(tags_list):
    if tags_list is None:
        return None
    return [t for t in tags_list if t is not None and t != ""]

def parse_index_lines(path):
    text = read_text(path)
    if text is None:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    return lines

def is_slug_filename(name):
    return re.match(r"^[a-z0-9-]+\.md$", name or "") is not None

def parse_search_results(path):
    text = read_text(path)
    if text is None:
        return {
            "headings": [],
            "bullets": []
        }
    lines = text.splitlines()
    headings = [ln.strip()[3:].strip() for ln in lines if ln.startswith("## ")]
    bullets = [ln.strip()[2:] for ln in lines if ln.startswith("- ")]
    return {
        "headings": headings,
        "bullets": bullets
    }

def parse_bullet_entry(entry):
    # Format: relative_path:line_number: context snippet
    # Do not enforce space after second colon strictly; compute based on first two colons
    s = entry
    first_colon = s.find(":")
    if first_colon == -1:
        return None
    second_colon = s.find(":", first_colon + 1)
    if second_colon == -1:
        return None
    path = s[:first_colon].strip()
    line_num_str = s[first_colon + 1:second_colon].strip()
    snippet = s[second_colon + 1:].strip()
    if not line_num_str.isdigit():
        return None
    return {
        "path": path,
        "line": int(line_num_str),
        "snippet": snippet
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    today_str = date.today().strftime("%Y-%m-%d")

    notes_root = os.path.join(output_dir, "notes")
    ideas_dir = os.path.join(notes_root, "ideas")
    projects_dir = os.path.join(notes_root, "projects")
    misc_dir = os.path.join(notes_root, "misc")
    daily_dir = os.path.join(notes_root, "daily")

    checks = {
        "dirs_exist": False,
        "notes_in_each_category": False,
        "slugs_valid": False,
        "frontmatter_present": False,
        "tags_present": False,
        "created_today": False,
        "heading_present": False,
        "appended_confidence_levels": False,
        "index_exists": False,
        "index_min_rows": False,
        "index_lines_well_formed": False,
        "index_paths_exist": False,
        "index_metadata_matches": False,
        "index_sorted": False,
        "search_exists": False,
        "search_has_terms": False,
        "search_has_bullet": False,
        "search_bullet_paths_valid": False,
        "search_snippet_length_ok": False,
        "daily_exists": False,
        "daily_heading_ok": False,
        "daily_two_entries": False,
    }

    # 1) Directories exist
    if os.path.isdir(ideas_dir) and os.path.isdir(projects_dir) and os.path.isdir(misc_dir) and os.path.isdir(daily_dir):
        checks["dirs_exist"] = True

    # Gather non-daily notes
    non_daily_dirs = [ideas_dir, projects_dir, misc_dir]
    non_daily_notes = []
    if checks["dirs_exist"]:
        for d in non_daily_dirs:
            if os.path.isdir(d):
                non_daily_notes.extend(list_md_files(d))

    # 2) At least one .md note exists in each of ideas, projects, misc
    has_ideas = len(list_md_files(ideas_dir)) > 0 if os.path.isdir(ideas_dir) else False
    has_projects = len(list_md_files(projects_dir)) > 0 if os.path.isdir(projects_dir) else False
    has_misc = len(list_md_files(misc_dir)) > 0 if os.path.isdir(misc_dir) else False
    if has_ideas and has_projects and has_misc:
        checks["notes_in_each_category"] = True

    # 3) Validate slugs, frontmatter, tags, created date, heading for non-daily notes
    slugs_ok = True
    frontmatter_ok_all = True
    tags_present_all = True
    created_today_all = True
    heading_present_all = True

    for f in non_daily_notes:
        base = os.path.basename(f)
        if not is_slug_filename(base):
            slugs_ok = False
        text = read_text(f)
        has_front, front_text, content_after = starts_with_frontmatter(text)
        if not has_front:
            frontmatter_ok_all = False
        else:
            tags = parse_tags_from_front(front_text or "")
            created = parse_created_from_front(front_text or "")
            if not tags or len(normalize_tags_list(tags)) == 0:
                tags_present_all = False
            if created != today_str:
                created_today_all = False
        if not has_level1_heading(content_after or ""):
            heading_present_all = False

    if non_daily_notes:
        if slugs_ok:
            checks["slugs_valid"] = True
        if frontmatter_ok_all:
            checks["frontmatter_present"] = True
        if tags_present_all:
            checks["tags_present"] = True
        if created_today_all:
            checks["created_today"] = True
        if heading_present_all:
            checks["heading_present"] = True

    # 4) Confirm at least one note contains '## Confidence levels'
    appended_found = False
    for f in non_daily_notes:
        t = read_text(f)
        if t and has_confidence_levels_heading(t):
            appended_found = True
            break
    if appended_found:
        checks["appended_confidence_levels"] = True

    # 5) Verify notes_index.tsv
    index_path = os.path.join(output_dir, "notes_index.tsv")
    if os.path.isfile(index_path):
        checks["index_exists"] = True
        lines = parse_index_lines(index_path)
        # All lines must be well-formed; require at least 3 lines
        well_formed = True
        paths = []
        titles = []
        tags_fields = []
        created_fields = []
        for ln in lines:
            parts = ln.split("\t")
            if len(parts) != 4:
                well_formed = False
                break
            rel_path = parts[0].strip()
            title = parts[1].strip()
            tags_str = parts[2].strip()
            created_str = parts[3].strip()
            # rel_path under notes/, not starting with slash, and not under daily/
            if rel_path.startswith("/") or not rel_path.startswith("notes/") or rel_path.startswith("notes/daily/"):
                well_formed = False
                break
            if not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", created_str):
                well_formed = False
                break
            paths.append(rel_path)
            titles.append(title)
            tags_fields.append(tags_str)
            created_fields.append(created_str)
        if len(lines) >= 3:
            checks["index_min_rows"] = True
        if well_formed and len(lines) >= 3:
            checks["index_lines_well_formed"] = True
            # paths exist and metadata matches
            paths_exist_all = True
            metadata_match_all = True
            for rel_path, tags_str, created_str in zip(paths, tags_fields, created_fields):
                abs_path = os.path.join(output_dir, rel_path)
                if not os.path.isfile(abs_path):
                    paths_exist_all = False
                    break
                # Parse frontmatter tags & created
                text = read_text(abs_path)
                has_front, front_text, _ = starts_with_frontmatter(text or "")
                if not has_front:
                    metadata_match_all = False
                    break
                fm_tags = parse_tags_from_front(front_text or "")
                fm_created = parse_created_from_front(front_text or "")
                index_tags = [p.strip() for p in tags_str.split(",") if p.strip() != ""]
                fm_tags_norm = normalize_tags_list(fm_tags or [])
                # Compare tags sets ignoring order
                if sorted(index_tags) != sorted(fm_tags_norm):
                    metadata_match_all = False
                    break
                if fm_created != created_str:
                    metadata_match_all = False
                    break
            if paths_exist_all:
                checks["index_paths_exist"] = True
            if metadata_match_all:
                checks["index_metadata_matches"] = True
            # sorted check by relative_path
            if paths == sorted(paths):
                checks["index_sorted"] = True

    # 6) Verify search_results.md
    search_path = os.path.join(output_dir, "search_results.md")
    if os.path.isfile(search_path):
        checks["search_exists"] = True
        search_data = parse_search_results(search_path)
        headings_unique = list({h for h in search_data["headings"] if h.strip() != ""})
        if len(headings_unique) >= 2:
            checks["search_has_terms"] = True
        # Validate bullets
        bullet_any = False
        bullet_path_valid = False
        bullet_snippet_ok = False
        for b in search_data["bullets"]:
            parsed = parse_bullet_entry(b)
            if not parsed:
                continue
            bullet_any = True
            path = parsed["path"]
            line_num = parsed["line"]
            snippet = parsed["snippet"]
            if path.startswith("notes/"):
                abs_path = os.path.join(output_dir, path)
                if os.path.isfile(abs_path):
                    bullet_path_valid = True
            if isinstance(line_num, int):  # numeric confirmed
                # snippet length between 50 and 200 characters
                if 50 <= len(snippet) <= 200:
                    bullet_snippet_ok = True
            # If all satisfied, no need to continue scanning
            if bullet_any and bullet_path_valid and bullet_snippet_ok:
                break
        if bullet_any:
            checks["search_has_bullet"] = True
        if bullet_path_valid:
            checks["search_bullet_paths_valid"] = True
        if bullet_snippet_ok:
            checks["search_snippet_length_ok"] = True

    # 7) Verify daily note
    daily_file = os.path.join(daily_dir, f"{today_str}.md")
    if os.path.isfile(daily_file):
        checks["daily_exists"] = True
        daily_text = read_text(daily_file) or ""
        daily_lines = daily_text.splitlines()
        # First non-empty line is '# YYYY-MM-DD'
        first_non_empty = None
        for ln in daily_lines:
            if ln.strip() != "":
                first_non_empty = ln.strip()
                break
        if first_non_empty == f"# {today_str}":
            checks["daily_heading_ok"] = True
        # At least two bullet entries matching '- HH:MM — '
        bullet_re = re.compile(r"^- ([01][0-9]|2[0-3]):[0-5][0-9] — .+")
        count_bullets = sum(1 for ln in daily_lines if bullet_re.match(ln.strip()) is not None)
        if count_bullets >= 2:
            checks["daily_two_entries"] = True

    # Compute reward as average of True checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0
    # No-op baseline: if output dir missing or empty, ensure 0.0
    # Here, if none of the checks passed, reward will be 0.0 already.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()