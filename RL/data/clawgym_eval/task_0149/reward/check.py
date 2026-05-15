import json
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_bracketed_list(value: str) -> List[str]:
    # value like ["a", "b", "c"]
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return []
    inner = value[1:-1].strip()
    if not inner:
        return []
    parts = []
    current = ""
    in_quote = False
    for ch in inner:
        if ch == '"' and (not current or current[-1] != "\\"):
            in_quote = not in_quote
            current += ch
        elif ch == "," and not in_quote:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current:
        parts.append(current.strip())
    result = []
    for p in parts:
        p = p.strip()
        if p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        result.append(p)
    return result


def parse_outline_yaml_simple(path: Path) -> Optional[Dict[str, Any]]:
    text = read_text_safe(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    platforms: List[str] = []
    chapters: List[Dict[str, Any]] = []
    in_chapters = False
    current: Optional[Dict[str, Any]] = None
    for raw in lines:
        line = raw.rstrip()
        if not in_chapters:
            if line.strip().startswith("platforms:"):
                # extract list
                try:
                    _, rhs = line.split(":", 1)
                    platforms = parse_bracketed_list(rhs.strip())
                except Exception:
                    platforms = []
            if line.strip() == "chapters:":
                in_chapters = True
            continue
        else:
            if line.startswith("  - "):
                # start new chapter
                if current:
                    chapters.append(current)
                current = {}
                # This line could contain something after '- ' but in our input it doesn't
                continue
            if current is not None and line.startswith("    "):
                # property line
                prop = line.strip()
                if ":" not in prop:
                    continue
                key, rhs = prop.split(":", 1)
                key = key.strip()
                rhs = rhs.strip()
                if rhs.startswith('["') or rhs.startswith("["):
                    current[key] = parse_bracketed_list(rhs)
                else:
                    # string value (possibly quoted)
                    if rhs.startswith('"') and rhs.endswith('"'):
                        rhs = rhs[1:-1]
                    current[key] = rhs
            else:
                # out of chapter block
                continue
    if current:
        chapters.append(current)
    if not platforms or not chapters:
        return None
    chapters_by_id: Dict[str, Dict[str, Any]] = {}
    for ch in chapters:
        cid = ch.get("id")
        title = ch.get("title")
        themes = ch.get("themes") if isinstance(ch.get("themes"), list) else []
        tags = ch.get("tags") if isinstance(ch.get("tags"), list) else []
        if cid and title:
            chapters_by_id[cid] = {
                "title": title,
                "themes": themes,
                "tags": tags,
            }
    if not chapters_by_id:
        return None
    return {"platforms": platforms, "chapters_by_id": chapters_by_id}


def load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        dict_rows: List[Dict[str, str]] = []
        for r in rows[1:]:
            # pad / trim to header length
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            elif len(r) > len(header):
                r = r[: len(header)]
            dict_rows.append({header[i]: r[i] for i in range(len(header))})
        return header, dict_rows
    except Exception:
        return None, None


def parse_int_safe(s: str) -> Optional[int]:
    try:
        return int(s.strip())
    except Exception:
        return None


def extract_outermost_quoted(text: str) -> Optional[str]:
    # Extract substring between the first and last double quote
    try:
        start = text.find('"')
        if start == -1:
            return None
        end = text.rfind('"')
        if end == -1 or end == start:
            return None
        return text[start + 1 : end]
    except Exception:
        return None


def split_semicolon_list(s: str) -> List[str]:
    items = [itm.strip() for itm in s.split(";")]
    # remove empty entries
    return [itm for itm in items if itm != ""]


def split_pipe_list(s: str) -> List[str]:
    items = [itm.strip() for itm in s.split("|")]
    return [itm for itm in items if itm != ""]


def build_characters_mapping(characters_data: Any) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    # Returns: chapter_id -> list of names in file order, and name -> chapters list
    by_chapter: Dict[str, List[str]] = {}
    by_name: Dict[str, List[str]] = {}
    if isinstance(characters_data, list):
        for entry in characters_data:
            try:
                name = entry.get("name")
                chapters = entry.get("chapters", [])
                if not isinstance(chapters, list):
                    chapters = []
                by_name[name] = chapters
                for cid in chapters:
                    by_chapter.setdefault(cid, []).append(name)
            except Exception:
                continue
    return by_chapter, by_name


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "posts_csv_exists_and_columns": 0.0,
        "posts_csv_row_count": 0.0,
        "platforms_distribution_even": 0.0,
        "per_chapter_two_posts": 0.0,
        "each_post_quote_offsets_and_text_valid": 0.0,
        "feedback_prompt_has_question_mark_all": 0.0,
        "tags_within_allowed_and_count": 0.0,
        "character_mentions_within_allowed_and_count": 0.0,
        "post_support_json_exists_and_length": 0.0,
        "post_support_cross_checks": 0.0,
        "support_evidence_fields_present_and_correct": 0.0,
    }

    # Load inputs
    manuscript_path = workspace / "input" / "manuscript_excerpt.md"
    outline_path = workspace / "input" / "outline.yaml"
    characters_path = workspace / "input" / "characters.json"

    manuscript_text = read_text_safe(manuscript_path)
    outline = parse_outline_yaml_simple(outline_path)
    characters_data = load_json_safe(characters_path)

    outline_ok = outline is not None
    manuscript_ok = manuscript_text is not None
    characters_ok = characters_data is not None

    allowed_platforms: List[str] = outline["platforms"] if outline_ok else []
    chapters_by_id: Dict[str, Dict[str, Any]] = outline["chapters_by_id"] if outline_ok else {}
    allowed_chapter_ids = set(chapters_by_id.keys())

    chars_by_chapter, chars_by_name = build_characters_mapping(characters_data) if characters_ok else ({}, {})

    # Load outputs
    posts_csv_path = workspace / "output" / "posts.csv"
    support_json_path = workspace / "output" / "post_support.json"

    header, rows = load_csv_dicts(posts_csv_path)

    expected_columns = [
        "post_id",
        "platform",
        "chapter_id",
        "post_text",
        "feedback_prompt",
        "tags",
        "character_mentions",
        "quote_start_offset",
        "quote_end_offset",
    ]

    # posts_csv_exists_and_columns
    if header is not None and header == expected_columns:
        scores["posts_csv_exists_and_columns"] = 1.0
    else:
        scores["posts_csv_exists_and_columns"] = 0.0

    # posts_csv_row_count
    if rows is not None and len(rows) == 6:
        scores["posts_csv_row_count"] = 1.0
    else:
        scores["posts_csv_row_count"] = 0.0

    # If no rows, set to empty list for following iterations
    if rows is None:
        rows = []

    # platforms_distribution_even
    platform_ok = False
    if rows and outline_ok:
        platform_counts: Dict[str, int] = {}
        invalid_platform = False
        for r in rows:
            p = r.get("platform", "").strip()
            platform_counts[p] = platform_counts.get(p, 0) + 1
            if p not in allowed_platforms:
                invalid_platform = True
        platform_ok = (not invalid_platform) and platform_counts.get("Twitter", 0) == 3 and platform_counts.get("Instagram", 0) == 3 and sum(platform_counts.values()) == 6
    scores["platforms_distribution_even"] = 1.0 if platform_ok else 0.0

    # per_chapter_two_posts
    per_chapter_ok = False
    if rows and outline_ok:
        ch_counts: Dict[str, int] = {}
        invalid_chapter = False
        for r in rows:
            cid = r.get("chapter_id", "").strip()
            ch_counts[cid] = ch_counts.get(cid, 0) + 1
            if cid not in allowed_chapter_ids:
                invalid_chapter = True
        per_chapter_ok = (not invalid_chapter) and ch_counts.get("ch1", 0) == 2 and ch_counts.get("ch2", 0) == 2 and ch_counts.get("ch3", 0) == 2 and sum(ch_counts.values()) == 6
    scores["per_chapter_two_posts"] = 1.0 if per_chapter_ok else 0.0

    # each_post_quote_offsets_and_text_valid (fraction per post)
    quote_checks_passed = 0
    if manuscript_ok and rows:
        for r in rows:
            start_s = r.get("quote_start_offset", "").strip()
            end_s = r.get("quote_end_offset", "").strip()
            post_text = r.get("post_text", "")
            start = parse_int_safe(start_s)
            end = parse_int_safe(end_s)
            if start is None or end is None:
                continue
            if start < 0 or end <= start or end > len(manuscript_text):
                continue
            sub = manuscript_text[start:end]
            quoted = extract_outermost_quoted(post_text)
            if quoted is None:
                continue
            if quoted == sub and len(sub) > 0:
                quote_checks_passed += 1
    scores["each_post_quote_offsets_and_text_valid"] = (quote_checks_passed / 6.0) if rows else 0.0

    # feedback_prompt_has_question_mark_all (fraction)
    prompt_passed = 0
    if rows:
        for r in rows:
            fp = r.get("feedback_prompt", "")
            if isinstance(fp, str) and "?" in fp and any(ch.strip() for ch in fp):
                prompt_passed += 1
    scores["feedback_prompt_has_question_mark_all"] = (prompt_passed / 6.0) if rows else 0.0

    # tags_within_allowed_and_count (fraction)
    tags_passed = 0
    if rows and outline_ok:
        for r in rows:
            cid = r.get("chapter_id", "").strip()
            tags_str = r.get("tags", "")
            tags = split_semicolon_list(tags_str)
            if len(tags) < 2 or len(tags) > 3:
                continue
            allowed_tags = set(chapters_by_id.get(cid, {}).get("tags", []))
            if not tags:
                continue
            if all(t in allowed_tags for t in tags):
                tags_passed += 1
    scores["tags_within_allowed_and_count"] = (tags_passed / 6.0) if rows else 0.0

    # character_mentions_within_allowed_and_count (fraction)
    chars_passed = 0
    if rows and characters_ok:
        for r in rows:
            cid = r.get("chapter_id", "").strip()
            mentions_str = r.get("character_mentions", "")
            mentions = split_pipe_list(mentions_str)
            if len(mentions) < 1 or len(mentions) > 2:
                continue
            allowed_names = set(chars_by_chapter.get(cid, []))
            if mentions and all(name in allowed_names for name in mentions):
                chars_passed += 1
    scores["character_mentions_within_allowed_and_count"] = (chars_passed / 6.0) if rows else 0.0

    # post_support_json_exists_and_length
    support_data = load_json_safe(support_json_path)
    if isinstance(support_data, list) and len(support_data) == 6:
        scores["post_support_json_exists_and_length"] = 1.0
    else:
        scores["post_support_json_exists_and_length"] = 0.0

    # Cross-checks between posts.csv and post_support.json
    cross_checks_score = 0.0
    evidence_score = 0.0
    if isinstance(support_data, list) and len(support_data) == 6 and rows and outline_ok and manuscript_ok and characters_ok:
        # Build index by post_id for CSV
        csv_by_id: Dict[str, Dict[str, str]] = {}
        post_ids_csv = set()
        for r in rows:
            pid = r.get("post_id", "").strip()
            if pid:
                post_ids_csv.add(pid)
                if pid not in csv_by_id:
                    csv_by_id[pid] = r

        # Build index by post_id for support
        support_by_id: Dict[str, Dict[str, Any]] = {}
        post_ids_support = set()
        for item in support_data:
            pid = item.get("post_id", "")
            if isinstance(pid, str) and pid:
                post_ids_support.add(pid)
                if pid not in support_by_id:
                    support_by_id[pid] = item

        # Require exact matching sets
        if post_ids_csv == post_ids_support and len(post_ids_csv) == 6:
            per_item_pass = 0
            per_evidence_pass = 0
            for pid in post_ids_csv:
                r = csv_by_id[pid]
                s = support_by_id[pid]
                # platform matches
                platform_match = s.get("platform", None) == r.get("platform", None)
                # chapter title matches the chapter_id mapping
                cid = r.get("chapter_id", "").strip()
                expected_title = chapters_by_id.get(cid, {}).get("title")
                chapter_title_match = s.get("chapter_title", None) == expected_title
                # source_file exact
                source_file_match = s.get("source_file", None) == "input/manuscript_excerpt.md"
                # quote_text equals substring defined by offsets
                start = parse_int_safe(r.get("quote_start_offset", ""))
                end = parse_int_safe(r.get("quote_end_offset", ""))
                quote_text_ok = False
                if start is not None and end is not None and 0 <= start < end <= len(manuscript_text):
                    expected_quote = manuscript_text[start:end]
                    quote_text_ok = s.get("quote_text", None) == expected_quote and len(expected_quote) > 0
                # allowed_tag_check boolean correctness
                tags = split_semicolon_list(r.get("tags", ""))
                allowed_tags = set(chapters_by_id.get(cid, {}).get("tags", []))
                expected_allowed_tag_check = len(tags) >= 2 and len(tags) <= 3 and all(t in allowed_tags for t in tags)
                allowed_tag_check_match = s.get("allowed_tag_check", None) is True and expected_allowed_tag_check
                # character_check boolean correctness
                mentions = split_pipe_list(r.get("character_mentions", ""))
                allowed_names = set(chars_by_chapter.get(cid, []))
                expected_character_check = len(mentions) >= 1 and len(mentions) <= 2 and all(m in allowed_names for m in mentions)
                character_check_match = s.get("character_check", None) is True and expected_character_check

                item_ok = all([
                    platform_match,
                    chapter_title_match,
                    source_file_match,
                    quote_text_ok,
                    allowed_tag_check_match,
                    character_check_match,
                ])
                if item_ok:
                    per_item_pass += 1

                # Evidence checks
                evidence = s.get("evidence", None)
                evidence_ok = False
                if isinstance(evidence, dict):
                    themes = evidence.get("chapter_themes", None)
                    chars_list = evidence.get("characters_in_chapter", None)
                    expected_themes = chapters_by_id.get(cid, {}).get("themes", [])
                    # Build expected characters in original file order for that chapter
                    expected_chars_list = chars_by_chapter.get(cid, [])
                    evidence_ok = (
                        isinstance(themes, list)
                        and isinstance(chars_list, list)
                        and themes == expected_themes
                        and chars_list == expected_chars_list
                    )
                if evidence_ok:
                    per_evidence_pass += 1

            cross_checks_score = per_item_pass / 6.0
            evidence_score = per_evidence_pass / 6.0
        else:
            cross_checks_score = 0.0
            evidence_score = 0.0
    else:
        cross_checks_score = 0.0
        evidence_score = 0.0

    scores["post_support_cross_checks"] = cross_checks_score
    scores["support_evidence_fields_present_and_correct"] = evidence_score

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()