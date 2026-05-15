import json
import re
import sys
from pathlib import Path


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        return json.loads(_safe_read_text(path))
    except Exception:
        return None


def _parse_note_tags(path: Path):
    try:
        text = _safe_read_text(path)
        if not text:
            return None
        title = None
        date = None
        tags = None
        lines = text.splitlines()
        for line in lines[:20]:
            m = re.match(r"\s*Title:\s*(.+)", line)
            if m:
                title = m.group(1).strip()
            m = re.match(r"\s*Date:\s*(\d{4}-\d{2}-\d{2})", line)
            if m:
                date = m.group(1).strip()
            m = re.match(r"\s*Tags:\s*(.+)", line)
            if m:
                tags = [t.strip().lower() for t in m.group(1).split(",") if t.strip()]
        if not (title and date and tags):
            return None
        return {"title": title, "date": date, "tags": tags}
    except Exception:
        return None


def _load_categories_mapping(cfg_path: Path):
    cfg = _safe_load_json(cfg_path)
    if not isinstance(cfg, dict):
        return None
    if "categories" in cfg and isinstance(cfg["categories"], dict):
        return cfg["categories"]
    if "category_tags" in cfg and isinstance(cfg["category_tags"], dict):
        return cfg["category_tags"]
    return None


def _compute_expected_from_notes(workspace: Path):
    notes_dir = workspace / "notes"
    if not notes_dir.exists():
        return None
    cfg_path = workspace / "config" / "settings.json"
    categories = _load_categories_mapping(cfg_path)
    if not isinstance(categories, dict):
        return None
    # Normalize mapping keys and tag keys
    cats = {}
    for cat_name, keys in categories.items():
        if isinstance(keys, list):
            cats[str(cat_name)] = [str(k).lower() for k in keys]
    note_paths = sorted(notes_dir.glob("*.md"))
    notes = []
    for p in note_paths:
        parsed = _parse_note_tags(p)
        if not parsed:
            return None
        notes.append(parsed)

    # Assign categories and aggregate
    counts = {}
    all_tags = set()
    for note in notes:
        for t in note["tags"]:
            all_tags.add(t)
        assigned = set()
        for cat_name, keys in cats.items():
            for key in keys:
                if key in note["tags"]:
                    assigned.add(cat_name)
                    break
        for cat in sorted(assigned):
            counts[cat] = counts.get(cat, 0) + 1

    expected = {
        "num_notes": len(notes),
        "category_counts": counts,
        "all_tags": sorted(all_tags),
    }
    return expected


def _extract_section_lines(text: str, header_label: str):
    lines = text.splitlines()
    header_idx = None
    header_re = re.compile(r"^\s*#*\s*" + re.escape(header_label) + r"\s*:?\s*$", re.IGNORECASE)
    for i, line in enumerate(lines):
        if header_re.match(line):
            header_idx = i
            break
    if header_idx is None:
        return []
    # Find next header index for the other known headers
    other_headers = ["Category counts", "All tags"]
    stops = []
    for i in range(header_idx + 1, len(lines)):
        for oh in other_headers:
            if oh.lower() == header_label.lower():
                continue
            if re.match(r"^\s*#*\s*" + re.escape(oh) + r"\s*:?\s*$", lines[i], re.IGNORECASE):
                stops.append(i)
                break
    end_idx = min(stops) if stops else len(lines)
    return lines[header_idx + 1 : end_idx]


def _find_category_line_count(lines, category_name):
    # Accept lines like "- Category: 3" or "Category: 3"
    pattern = re.compile(r"^\s*(?:[-*]\s+)?(" + re.escape(category_name) + r")\s*:\s*(\d+)\s*$")
    for line in lines:
        m = pattern.match(line)
        if m:
            try:
                return int(m.group(2))
            except Exception:
                return None
    return None


def _extract_tag_sequence(lines, allowed_tags):
    # Build sequence of tags (from allowed_tags) in first-appearance order within section lines
    seq = []
    seen = set()
    token_re = re.compile(r"\b[a-z][a-z0-9\-]*\b")
    allowed = set(allowed_tags)
    for line in lines:
        for tok in token_re.findall(line.lower()):
            if tok in allowed and tok not in seen:
                seen.add(tok)
                seq.append(tok)
    return seq


def _parse_email_bullet_section(text: str):
    lines = text.splitlines()
    # Find the line with "Category summary:"
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "category summary:":
            start_idx = i
            break
    if start_idx is None:
        return []
    # Collect contiguous bullet lines starting with "- "
    bullets = []
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^\s*-\s+.+", lines[j]):
            bullets.append(lines[j].strip())
        else:
            # Stop at first non-bullet line
            break
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "first_run_error_captured": 0.0,
        "index_json_exists_and_valid": 0.0,
        "build_stdout_captured": 0.0,
        "summary_md_sections_and_content": 0.0,
        "email_subject_and_length": 0.0,
        "email_category_summary_bullets": 0.0,
        "sms_single_line_reopen_and_counts": 0.0,
    }

    # Check first run error capture
    first_err_path = workspace / "out" / "first_run_errors.txt"
    if first_err_path.exists():
        err_text = _safe_read_text(first_err_path)
        # Expect at least "Error: 'categories'"
        if "Error:" in err_text and "'categories'" in err_text:
            scores["first_run_error_captured"] = 1.0

    # Validate out/index.json
    index_path = workspace / "out" / "index.json"
    index_data = _safe_load_json(index_path) if index_path.exists() else None
    expected = _compute_expected_from_notes(workspace)
    index_valid = False
    if isinstance(index_data, dict) and expected is not None:
        # Structural checks
        has_keys = ("notes" in index_data and isinstance(index_data.get("notes"), list) and
                    "category_counts" in index_data and isinstance(index_data.get("category_counts"), dict) and
                    "all_tags" in index_data and isinstance(index_data.get("all_tags"), list))
        if has_keys:
            # Compare counts and tags strictly
            counts_ok = index_data["category_counts"] == expected["category_counts"]
            tags_ok = index_data["all_tags"] == expected["all_tags"]
            num_notes_ok = len(index_data["notes"]) == expected["num_notes"]
            if counts_ok and tags_ok and num_notes_ok:
                index_valid = True
    if index_valid:
        scores["index_json_exists_and_valid"] = 1.0

    # Validate build stdout captured
    stdout_path = workspace / "out" / "build_stdout.txt"
    if stdout_path.exists() and index_valid:
        stdout_text = _safe_read_text(stdout_path)
        ok = True
        # Expect "Indexed X notes."
        expected_indexed_line = f"Indexed {expected['num_notes']} notes."
        if expected_indexed_line not in stdout_text:
            ok = False
        # Expect "Category counts:" and each "- Cat: count"
        if "Category counts:" not in stdout_text:
            ok = False
        for cat, cnt in expected["category_counts"].items():
            line = f"- {cat}: {cnt}"
            if line not in stdout_text:
                ok = False
                break
        # Expect "Wrote out/index.json"
        if "Wrote out/index.json" not in stdout_text:
            ok = False
        if ok:
            scores["build_stdout_captured"] = 1.0

    # Validate summary.md content based on out/index.json
    summary_path = workspace / "out" / "summary.md"
    if summary_path.exists() and index_valid:
        summary_text = _safe_read_text(summary_path)
        # Extract sections
        cat_lines = _extract_section_lines(summary_text, "Category counts")
        tags_lines = _extract_section_lines(summary_text, "All tags")
        if cat_lines and tags_lines:
            # Check each category count line exists and matches
            cats_ok = True
            for cat, cnt in expected["category_counts"].items():
                found_cnt = _find_category_line_count(cat_lines, cat)
                if found_cnt is None or found_cnt != cnt:
                    cats_ok = False
                    break
            # Check tags are listed and sorted matching index 'all_tags'
            tags_seq = _extract_tag_sequence(tags_lines, index_data["all_tags"])
            tags_ok = tags_seq == index_data["all_tags"]
            if cats_ok and tags_ok:
                scores["summary_md_sections_and_content"] = 1.0

    # Validate announcement_email.txt
    email_path = workspace / "communications" / "announcement_email.txt"
    if email_path.exists():
        email_text = _safe_read_text(email_path)
        email_lines = email_text.splitlines()
        subject_ok = False
        body_len_ok = False
        if email_lines:
            if email_lines[0].startswith("Subject: "):
                subject_ok = True
            body_words = []
            for line in email_lines[1:]:
                body_words.extend(line.strip().split())
            if len(body_words) <= 180:
                body_len_ok = True
        if subject_ok and body_len_ok:
            scores["email_subject_and_length"] = 1.0

        # Check Category summary bullet list matches exactly expected
        if index_valid:
            bullets = _parse_email_bullet_section(email_text)
            if bullets:
                # Build set of expected bullet lines
                expected_set = set([f"- {cat}: {cnt}" for cat, cnt in expected["category_counts"].items()])
                found_set = set()
                for b in bullets:
                    m = re.match(r"^-\s+(.*?):\s*(\d+)\s*$", b)
                    if m:
                        name = m.group(1)
                        num = int(m.group(2))
                        found_set.add(f"- {name}: {num}")
                if found_set == expected_set:
                    scores["email_category_summary_bullets"] = 1.0

    # Validate announcement_sms.txt
    sms_path = workspace / "communications" / "announcement_sms.txt"
    if sms_path.exists() and index_valid:
        sms_text = _safe_read_text(sms_path).strip("\n")
        # Single line constraint
        lines = sms_text.splitlines()
        single_line_ok = len(lines) == 1
        length_ok = len(sms_text) <= 320
        # Mentions reopening
        reopen_ok = bool(re.search(r"reopen", sms_text, re.IGNORECASE))
        # Contains category counts "CategoryName: count" separated by semicolons
        counts_ok = False
        segments = [seg.strip() for seg in sms_text.split(";")]
        found = {}
        for seg in segments:
            m = re.match(r"^(.*?):\s*(\d+)\s*$", seg)
            if m:
                name = m.group(1)
                num = int(m.group(2))
                found[name] = num
        # Verify all expected categories are present with correct counts
        if all(name in found and found[name] == cnt for name, cnt in expected["category_counts"].items()):
            # If multiple categories exist, ensure at least one semicolon separates items
            if len(expected["category_counts"]) <= 1 or ";" in sms_text:
                counts_ok = True
        if single_line_ok and length_ok and reopen_ok and counts_ok:
            scores["sms_single_line_reopen_and_counts"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()