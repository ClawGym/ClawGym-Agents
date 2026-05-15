import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import Tuple, List, Dict, Optional


ALLOWED_EMOJIS = {"🔬", "🧪", "🧬", "🌿", "✨", "📚", "👍", "🤔"}


def _safe_read_text(path: Path) -> Tuple[bool, Optional[str]]:
    try:
        data = path.read_text(encoding="utf-8")
        return True, data
    except Exception:
        return False, None


def _safe_read_csv(path: Path) -> Tuple[bool, Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return True, [], []
            # Re-open for DictReader using same header
            f.seek(0)
            dict_reader = csv.DictReader(f)
            rows = []
            for row in dict_reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return True, header, rows
    except Exception:
        return False, None, None


def _parse_lesson_outline(path: Path) -> Tuple[bool, Optional[Dict[str, str]], Optional[set]]:
    ok, text = _safe_read_text(path)
    if not ok or text is None:
        return False, None, None
    topic_to_hashtag: Dict[str, str] = {}
    topic_ids: set = set()
    last_topic: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("TopicID:"):
            tid = line.split("TopicID:", 1)[1].strip()
            last_topic = tid
            if tid:
                topic_ids.add(tid)
        elif line.startswith("SuggestedHashtag:"):
            hashtag = line.split("SuggestedHashtag:", 1)[1].strip()
            if last_topic:
                topic_to_hashtag[last_topic] = hashtag
                # Do not reset last_topic to allow for safety if multiple fields; ordering is consistent in input
    return True, topic_to_hashtag, topic_ids


def _parse_calendar_dates(path: Path) -> Tuple[bool, Optional[List[str]]]:
    ok, header, rows = _safe_read_csv(path)
    if not ok or header is None or rows is None:
        return False, None
    # Expect header contains 'date'
    if "date" not in header:
        # attempt to handle cases where only one column named date exists but with whitespace
        return False, None
    dates: List[str] = []
    for r in rows:
        if "date" not in r:
            return False, None
        val = r["date"]
        if val is None:
            return False, None
        val = val.strip()
        if val != "":
            dates.append(val)
    return True, dates


def _parse_posts_csv(path: Path) -> Tuple[bool, Optional[List[str]], Optional[List[Dict[str, str]]]]:
    return _safe_read_csv(path)


def _get_headings_positions(md_text: str) -> List[Tuple[int, str]]:
    headings: List[Tuple[int, str]] = []
    for idx, raw_line in enumerate(md_text.splitlines()):
        line = raw_line.rstrip("\n")
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
        if m:
            heading = m.group(2).strip()
            headings.append((idx, heading))
    return headings


def _extract_section(md_text: str, heading_name: str) -> Tuple[bool, Optional[List[str]]]:
    lines = md_text.splitlines()
    headings = _get_headings_positions(md_text)
    # Find the heading index with exact name match
    target_idx = None
    for idx, h in headings:
        if h == heading_name:
            target_idx = idx
            break
    if target_idx is None:
        return False, None
    # Find next heading index
    next_idx = None
    for idx, h in headings:
        if idx > target_idx:
            next_idx = idx
            break
    section_lines = lines[target_idx + 1: next_idx] if next_idx is not None else lines[target_idx + 1:]
    return True, section_lines


def _parse_misconceptions_bullets(section_lines: List[str]) -> Dict[str, str]:
    # Pattern: "- TOPIC_ID: short note"
    mapping: Dict[str, str] = {}
    for raw in section_lines:
        line = raw.strip()
        m = re.match(r"^-\s*([A-Za-z0-9\-]+):\s*(.+)\s*$", line)
        if m:
            tid = m.group(1).strip()
            note = m.group(2).strip()
            mapping[tid] = note
    return mapping


def _contains_allowed_emoji(text: str) -> bool:
    return any(ch in ALLOWED_EMOJIS for ch in text)


def _contains_link_like(text: str) -> bool:
    t = text.lower()
    # simple heuristics: http://, https://, www., or something like example.com
    if "http://" in t or "https://" in t or "www." in t or "://" in t:
        return True
    # Common TLDs
    for tld in [".com", ".org", ".net", ".edu", ".io", ".co", ".gov"]:
        if tld in t:
            return True
    return False


def _run_validator(workspace: Path) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    validate_py = workspace / "validate.py"
    if not validate_py.exists():
        return False, None, None, None
    try:
        proc = subprocess.run(
            [sys.executable, str(validate_py.name)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            text=True,
            encoding="utf-8",
        )
        return True, proc.returncode, proc.stdout, proc.stderr
    except Exception:
        return False, None, None, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "posts_csv_has_required_columns_order": 0.0,
        "posts_dates_match_calendar": 0.0,
        "topic_ids_in_posts_are_valid": 0.0,
        "post_text_length_limit": 0.0,
        "post_text_emojis_allowed_present": 0.0,
        "post_text_no_links": 0.0,
        "hashtags_include_required_and_min_two": 0.0,
        "reading_grade_estimate_range": 0.0,
        "target_audience_values_valid": 0.0,
        "summary_report_has_required_headings": 0.0,
        "summary_misconceptions_covers_used_topics": 0.0,
        "summary_misconceptions_notes_match_corrections": 0.0,
        "validator_script_exists": 0.0,
        "validator_run_exit_zero": 0.0,
        "validation_log_matches_stdout": 0.0,
    }

    # Load inputs
    lesson_outline = workspace / "input" / "lesson_outline.md"
    misconceptions_csv = workspace / "input" / "misconceptions.csv"
    calendar_csv = workspace / "input" / "calendar.csv"

    posts_csv = workspace / "out" / "posts.csv"
    summary_report_md = workspace / "out" / "summary_report.md"
    validation_log_txt = workspace / "out" / "validation_log.txt"

    ok_outline, topic_to_hashtag, topic_ids = _parse_lesson_outline(lesson_outline)
    ok_calendar, calendar_dates = _parse_calendar_dates(calendar_csv)
    ok_posts, posts_header, posts_rows = _parse_posts_csv(posts_csv)

    # posts_csv_has_required_columns_order
    expected_header = ["date", "topic_id", "post_text", "hashtags", "reading_grade_estimate", "target_audience"]
    if ok_posts and posts_header is not None:
        if posts_header == expected_header:
            scores["posts_csv_has_required_columns_order"] = 1.0
        else:
            scores["posts_csv_has_required_columns_order"] = 0.0
    else:
        scores["posts_csv_has_required_columns_order"] = 0.0

    # posts_dates_match_calendar
    if ok_posts and posts_rows is not None and ok_calendar and calendar_dates is not None:
        # Require exactly one row for each date and no extras
        date_counts: Dict[str, int] = {}
        for r in posts_rows:
            d = (r.get("date") or "").strip()
            date_counts[d] = date_counts.get(d, 0) + 1
        all_calendar_set = set(calendar_dates)
        posts_date_set = set(date_counts.keys())
        no_extra = posts_date_set == all_calendar_set
        all_once = all(date_counts.get(d, 0) == 1 for d in calendar_dates)
        counts_match = len(posts_rows) == len(calendar_dates)
        if no_extra and all_once and counts_match:
            scores["posts_dates_match_calendar"] = 1.0
        else:
            scores["posts_dates_match_calendar"] = 0.0
    else:
        scores["posts_dates_match_calendar"] = 0.0

    # topic_ids_in_posts_are_valid
    if ok_posts and posts_rows is not None and ok_outline and topic_ids is not None:
        total = len(posts_rows)
        if total > 0:
            valid = 0
            for r in posts_rows:
                tid = (r.get("topic_id") or "").strip()
                if tid in topic_ids:
                    valid += 1
            scores["topic_ids_in_posts_are_valid"] = valid / total
        else:
            scores["topic_ids_in_posts_are_valid"] = 0.0
    else:
        scores["topic_ids_in_posts_are_valid"] = 0.0

    # post_text_length_limit, post_text_emojis_allowed_present, post_text_no_links
    if ok_posts and posts_rows is not None:
        total = len(posts_rows)
        if total > 0:
            len_ok = 0
            emoji_ok = 0
            nolink_ok = 0
            for r in posts_rows:
                text = (r.get("post_text") or "")
                if len(text) <= 280:
                    len_ok += 1
                if _contains_allowed_emoji(text):
                    emoji_ok += 1
                # Check for links in post_text only
                if not _contains_link_like(text):
                    nolink_ok += 1
            scores["post_text_length_limit"] = len_ok / total
            scores["post_text_emojis_allowed_present"] = emoji_ok / total
            scores["post_text_no_links"] = nolink_ok / total
        else:
            scores["post_text_length_limit"] = 0.0
            scores["post_text_emojis_allowed_present"] = 0.0
            scores["post_text_no_links"] = 0.0
    else:
        scores["post_text_length_limit"] = 0.0
        scores["post_text_emojis_allowed_present"] = 0.0
        scores["post_text_no_links"] = 0.0

    # hashtags_include_required_and_min_two
    if ok_posts and posts_rows is not None and ok_outline and topic_to_hashtag is not None:
        total = len(posts_rows)
        if total > 0:
            ok_count = 0
            for r in posts_rows:
                tid = (r.get("topic_id") or "").strip()
                tags_field = (r.get("hashtags") or "")
                tokens = [t.strip() for t in tags_field.split(",") if t.strip() != ""]
                has_bio = "#BioClass" in tokens
                has_suggested = False
                suggested = topic_to_hashtag.get(tid)
                if suggested is not None:
                    has_suggested = suggested in tokens
                # Also ensure no links in hashtags to avoid external references sneaking in
                no_links_in_tags = not _contains_link_like(tags_field)
                if len(tokens) >= 2 and has_bio and has_suggested and no_links_in_tags:
                    ok_count += 1
            scores["hashtags_include_required_and_min_two"] = ok_count / total
        else:
            scores["hashtags_include_required_and_min_two"] = 0.0
    else:
        scores["hashtags_include_required_and_min_two"] = 0.0

    # reading_grade_estimate_range
    if ok_posts and posts_rows is not None:
        total = len(posts_rows)
        if total > 0:
            ok_count = 0
            for r in posts_rows:
                val = (r.get("reading_grade_estimate") or "").strip()
                try:
                    iv = int(val)
                    if 6 <= iv <= 10 and str(iv) == val or (val.startswith("0") and int(val) == iv):
                        # Accept integers even if zero-padded (e.g., "06")
                        if 6 <= iv <= 10:
                            ok_count += 1
                except Exception:
                    pass
            scores["reading_grade_estimate_range"] = ok_count / total
        else:
            scores["reading_grade_estimate_range"] = 0.0
    else:
        scores["reading_grade_estimate_range"] = 0.0

    # target_audience_values_valid
    if ok_posts and posts_rows is not None:
        total = len(posts_rows)
        if total > 0:
            ok_count = 0
            for r in posts_rows:
                val = (r.get("target_audience") or "").strip()
                if val in ("students", "parents"):
                    ok_count += 1
            scores["target_audience_values_valid"] = ok_count / total
        else:
            scores["target_audience_values_valid"] = 0.0
    else:
        scores["target_audience_values_valid"] = 0.0

    # summary_report checks
    ok_summary, summary_text = _safe_read_text(summary_report_md)
    required_headings = ["Plan Overview", "Alignment", "Misconceptions addressed", "Schedule"]
    if ok_summary and summary_text is not None:
        headings = _get_headings_positions(summary_text)
        present = set(h for _, h in headings)
        if all(h in present for h in required_headings):
            scores["summary_report_has_required_headings"] = 1.0
        else:
            scores["summary_report_has_required_headings"] = 0.0

        # Extract misconceptions section
        sec_ok, sec_lines = _extract_section(summary_text, "Misconceptions addressed")
        if sec_ok and sec_lines is not None and ok_posts and posts_rows is not None:
            bullet_map = _parse_misconceptions_bullets(sec_lines)
            used_topic_ids = set((r.get("topic_id") or "").strip() for r in posts_rows)
            used_topic_ids.discard("")  # remove empty if any
            if len(used_topic_ids) == 0:
                # If no topics used, coverage trivially zero
                scores["summary_misconceptions_covers_used_topics"] = 0.0
                scores["summary_misconceptions_notes_match_corrections"] = 0.0
            else:
                # Coverage check
                if used_topic_ids.issubset(set(bullet_map.keys())):
                    # Ensure at least all used topics are covered (no need to prohibit extras)
                    scores["summary_misconceptions_covers_used_topics"] = 1.0
                else:
                    scores["summary_misconceptions_covers_used_topics"] = 0.0
                # Corrections match
                ok_mis, mis_header, mis_rows = _safe_read_csv(misconceptions_csv)
                if ok_mis and mis_header is not None and mis_rows is not None:
                    corr_map: Dict[str, str] = {}
                    for row in mis_rows:
                        tid = (row.get("topic_id") or "").strip()
                        corr = (row.get("correction") or "").strip()
                        if tid:
                            corr_map[tid] = corr
                    total = len(used_topic_ids)
                    if total > 0:
                        correct = 0
                        for tid in used_topic_ids:
                            bullet_note = bullet_map.get(tid, "").strip()
                            expected = corr_map.get(tid, "").strip()
                            if bullet_note != "" and expected != "" and bullet_note == expected:
                                correct += 1
                        scores["summary_misconceptions_notes_match_corrections"] = correct / total
                    else:
                        scores["summary_misconceptions_notes_match_corrections"] = 0.0
                else:
                    scores["summary_misconceptions_notes_match_corrections"] = 0.0
        else:
            scores["summary_misconceptions_covers_used_topics"] = 0.0
            scores["summary_misconceptions_notes_match_corrections"] = 0.0
    else:
        scores["summary_report_has_required_headings"] = 0.0
        scores["summary_misconceptions_covers_used_topics"] = 0.0
        scores["summary_misconceptions_notes_match_corrections"] = 0.0

    # validator checks
    validate_py = workspace / "validate.py"
    scores["validator_script_exists"] = 1.0 if validate_py.exists() and validate_py.is_file() else 0.0

    ran, rc, stdout, stderr = _run_validator(workspace)
    if ran and rc is not None and stdout is not None:
        scores["validator_run_exit_zero"] = 1.0 if rc == 0 else 0.0
        # Compare validation log
        ok_log, log_text = _safe_read_text(validation_log_txt)
        if ok_log and log_text is not None:
            # Exact stdout match
            if log_text == stdout:
                scores["validation_log_matches_stdout"] = 1.0
            else:
                scores["validation_log_matches_stdout"] = 0.0
        else:
            scores["validation_log_matches_stdout"] = 0.0
    else:
        scores["validator_run_exit_zero"] = 0.0
        scores["validation_log_matches_stdout"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()