import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict((k.strip(), v if v is not None else "") for k, v in row.items()) for row in reader]
        return rows
    except Exception:
        return None


def _parse_bulleted_list_after_heading(md_text: str, heading_substring: str) -> List[str]:
    items: List[str] = []
    lines = md_text.splitlines()
    inside = False
    found_heading = False
    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not found_heading and heading_substring.lower() in line.lower():
            found_heading = True
            inside = True
            continue
        if inside:
            if line.startswith("- "):
                items.append(line[2:].strip())
            else:
                # Stop when bullets have ended
                if len(items) > 0:
                    break
                # If hit non-bullet line before collecting any, keep scanning in case bullets start later
                continue
    return items


def _compute_theme_averages(prior_posts: List[Dict]) -> Dict[str, float]:
    sums: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for p in prior_posts:
        try:
            theme = str(p.get("theme", "")).strip()
            score = float(p.get("engagement_score"))
        except Exception:
            continue
        if theme:
            sums[theme] = sums.get(theme, 0.0) + score
            counts[theme] = counts.get(theme, 0) + 1
    averages = {}
    for theme, total in sums.items():
        if counts.get(theme, 0) > 0:
            averages[theme] = total / counts[theme]
    return averages


def _top_two_themes_by_avg(averages: Dict[str, float]) -> List[Tuple[str, float]]:
    # Return list of (theme, avg) sorted desc by avg, take up to 2
    sorted_items = sorted(averages.items(), key=lambda kv: (-kv[1], kv[0]))
    return sorted_items[:2]


def _count_words(text: str) -> int:
    # Count sequences of word characters as words
    return len(re.findall(r"\b\w+\b", text))


def _extract_bullet_lines(md_text: str) -> List[str]:
    bullets = []
    for line in md_text.splitlines():
        s = line.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s)
    return bullets


def _csv_expect_header(path: Path, expected_header: List[str]) -> Tuple[bool, Optional[List[Dict[str, str]]]]:
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return False, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return False, None
    if header is None:
        return False, None
    normalized_header = [h.strip() for h in header]
    if normalized_header != expected_header:
        return False, rows
    return True, rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "content_calendar_exists_and_header": 0.0,
        "content_calendar_row_count_and_weeks_structure": 0.0,
        "content_calendar_channels_valid_and_mixed": 0.0,
        "book_fields_match_books_csv": 0.0,
        "periods_variety_coverage": 0.0,
        "themes_top_two_usage_count": 0.0,
        "prior_post_ids_valid_and_minimum": 0.0,
        "hooks_start_with_valid_starters": 0.0,
        "ctas_valid_options": 0.0,
        "reasons_brief_and_data_or_notes_based": 0.0,
        "status_summary_word_count": 0.0,
        "status_summary_includes_top_themes_and_avgs": 0.0,
        "status_summary_lists_periods_covered": 0.0,
        "status_summary_has_three_bullets": 0.0,
        "status_summary_mentions_goals_notes": 0.0,
        "rewrites_json_structure": 0.0,
        "rewrites_teen_friendly_constraints": 0.0,
        "rewrites_parent_friendly_constraints": 0.0,
    }

    # Input files
    books_path = workspace / "input" / "books.csv"
    prior_posts_path = workspace / "input" / "prior_posts.json"
    notes_path = workspace / "input" / "notes.md"
    draft_dm_path = workspace / "input" / "draft_dm.txt"

    # Output files
    calendar_path = workspace / "output" / "content_calendar.csv"
    summary_path = workspace / "output" / "status_summary.md"
    rewrites_path = workspace / "output" / "rewrites.json"

    # Load inputs
    books_rows = _safe_read_csv_dicts(books_path)
    prior_posts = _safe_load_json(prior_posts_path)
    notes_md = _safe_read_text(notes_path)
    _ = _safe_read_text(draft_dm_path)  # draft exists but not directly graded here

    # Prepare parsed inputs
    book_by_id: Dict[str, Dict[str, str]] = {}
    period_by_id: Dict[str, str] = {}
    title_by_id: Dict[str, str] = {}
    if books_rows:
        for r in books_rows:
            bid = str(r.get("book_id", "")).strip()
            if bid:
                book_by_id[bid] = r
                period_by_id[bid] = str(r.get("period", "")).strip()
                title_by_id[bid] = str(r.get("title", "")).strip()

    prior_ids = set()
    theme_averages: Dict[str, float] = {}
    top_two: List[Tuple[str, float]] = []
    if isinstance(prior_posts, list):
        for p in prior_posts:
            pid = str(p.get("id", "")).strip()
            if pid:
                prior_ids.add(pid)
        theme_averages = _compute_theme_averages(prior_posts)
        top_two = _top_two_themes_by_avg(theme_averages)

    hook_starters: List[str] = []
    cta_options: List[str] = []
    if notes_md:
        hook_starters = _parse_bulleted_list_after_heading(notes_md, "Hook starters")
        cta_options = _parse_bulleted_list_after_heading(notes_md, "CTA options")

    # Validate content_calendar.csv
    expected_header = [
        "week",
        "slot",
        "channel",
        "book_id",
        "title",
        "historical_period",
        "theme",
        "hook",
        "main_idea",
        "CTA",
        "prior_post_id",
        "reason",
    ]
    header_ok, calendar_rows = _csv_expect_header(calendar_path, expected_header)
    if header_ok:
        scores["content_calendar_exists_and_header"] = 1.0

    if header_ok and calendar_rows is not None:
        # Exactly 8 rows and 2 per week (weeks 1-4)
        week_counts: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
        valid_weeks = True
        for r in calendar_rows:
            w_raw = str(r.get("week", "")).strip()
            try:
                w = int(w_raw)
            except Exception:
                valid_weeks = False
                break
            if w not in (1, 2, 3, 4):
                valid_weeks = False
                break
            week_counts[w] = week_counts.get(w, 0) + 1
        if len(calendar_rows) == 8 and valid_weeks and all(week_counts.get(i, 0) == 2 for i in (1, 2, 3, 4)):
            scores["content_calendar_row_count_and_weeks_structure"] = 1.0

        # Channel validity and mixed usage
        channels_valid = True
        channels_seen = set()
        for r in calendar_rows:
            ch = str(r.get("channel", "")).strip()
            if ch not in {"Instagram", "TikTok"}:
                channels_valid = False
                break
            channels_seen.add(ch)
        if channels_valid and len(channels_seen) >= 2:
            scores["content_calendar_channels_valid_and_mixed"] = 1.0

        # Book fields validation and periods variety
        all_books_match = True
        used_periods: List[str] = []
        for r in calendar_rows:
            bid = str(r.get("book_id", "")).strip()
            t = str(r.get("title", "")).strip()
            hp = str(r.get("historical_period", "")).strip()
            if bid not in book_by_id:
                all_books_match = False
                break
            expected_title = title_by_id.get(bid, "")
            expected_period = period_by_id.get(bid, "")
            if t != expected_title or hp != expected_period:
                all_books_match = False
                break
            if hp:
                used_periods.append(hp)
        if all_books_match:
            scores["book_fields_match_books_csv"] = 1.0
        if len(set(used_periods)) >= 4:
            scores["periods_variety_coverage"] = 1.0

        # Top two theme usage (at least 4 rows use one of the top two themes by average engagement)
        top_theme_names = {name for name, _avg in top_two}
        if top_theme_names and len(top_theme_names) >= 1:
            count_top_theme_rows = 0
            for r in calendar_rows:
                th = str(r.get("theme", "")).strip()
                if th in top_theme_names:
                    count_top_theme_rows += 1
            if count_top_theme_rows >= 4:
                scores["themes_top_two_usage_count"] = 1.0

        # prior_post_id validity and minimum 4
        valid_prior_count = 0
        any_invalid_nonempty = False
        for r in calendar_rows:
            pid = str(r.get("prior_post_id", "")).strip()
            if pid:
                if pid in prior_ids:
                    valid_prior_count += 1
                else:
                    any_invalid_nonempty = True
        if valid_prior_count >= 4 and not any_invalid_nonempty:
            scores["prior_post_ids_valid_and_minimum"] = 1.0

        # Hooks start with valid starters
        hooks_ok = True
        if hook_starters:
            for r in calendar_rows:
                hook = str(r.get("hook", "")).lstrip()
                if not any(hook.startswith(starter) for starter in hook_starters):
                    hooks_ok = False
                    break
            if hooks_ok:
                scores["hooks_start_with_valid_starters"] = 1.0

        # CTA validity
        ctas_ok = True
        if cta_options:
            for r in calendar_rows:
                cta = str(r.get("CTA", "")).strip()
                if cta not in set(cta_options):
                    ctas_ok = False
                    break
            if ctas_ok:
                scores["ctas_valid_options"] = 1.0

        # Reasons brief and data/notes based
        # Deterministic heuristic: non-empty and contains at least one keyword indicating data/notes usage
        keywords = {"theme", "period", "top", "engagement", "notes", "variety", "family", "discussion", "CTA", "timeline"}
        reasons_ok = True
        for r in calendar_rows:
            reason = str(r.get("reason", "")).strip()
            if len(reason) < 10:
                reasons_ok = False
                break
            lower = reason.lower()
            if not any(k in lower for k in keywords):
                reasons_ok = False
                break
        if reasons_ok:
            scores["reasons_brief_and_data_or_notes_based"] = 1.0

    # Validate status_summary.md
    summary_text = _safe_read_text(summary_path)
    if summary_text:
        wc = _count_words(summary_text)
        if 200 <= wc <= 300:
            scores["status_summary_word_count"] = 1.0

        # Top two themes mention with rounded averages
        if len(top_two) == 2:
            theme1, avg1 = top_two[0]
            theme2, avg2 = top_two[1]
            r1 = int(round(avg1))
            r2 = int(round(avg2))
            lower_sum = summary_text.lower()
            t1_present = theme1.lower() in lower_sum
            t2_present = theme2.lower() in lower_sum
            nums_present = (str(r1) in summary_text) and (str(r2) in summary_text)
            if t1_present and t2_present and nums_present:
                scores["status_summary_includes_top_themes_and_avgs"] = 1.0

        # Lists the distinct historical periods covered in the calendar
        if header_ok and calendar_rows is not None:
            used_periods_set = set()
            for r in calendar_rows:
                hp = str(r.get("historical_period", "")).strip()
                if hp:
                    used_periods_set.add(hp)
            lower_sum = summary_text.lower()
            if used_periods_set and all(p.lower() in lower_sum for p in used_periods_set):
                scores["status_summary_lists_periods_covered"] = 1.0

        # Exactly 3 bullet points for risks/assumptions
        bullets = _extract_bullet_lines(summary_text)
        if len(bullets) == 3:
            scores["status_summary_has_three_bullets"] = 1.0

        # Mentions goals: reading list and Family Discussion Night
        ls = summary_text.lower()
        mentions_reading_list = "reading list" in ls
        mentions_family_night = ("family discussion night" in ls) or ("family night" in ls) or ("discussion night" in ls)
        if mentions_reading_list and mentions_family_night:
            scores["status_summary_mentions_goals_notes"] = 1.0

    # Validate rewrites.json
    rewrites = _safe_load_json(rewrites_path)
    if isinstance(rewrites, dict) and "teen_friendly" in rewrites and "parent_friendly" in rewrites:
        if isinstance(rewrites.get("teen_friendly"), str) and isinstance(rewrites.get("parent_friendly"), str):
            scores["rewrites_json_structure"] = 1.0

        # CTA options from notes
        cta_set = set(cta_options) if cta_options else set()

        def _check_msg_constraints(msg: str) -> bool:
            if not isinstance(msg, str):
                return False
            if _count_words(msg) > 120:
                return False
            if cta_set:
                # At least one CTA present as exact substring
                if not any(cta in msg for cta in cta_set):
                    return False
            else:
                # If no CTA options could be parsed, fail this check deterministically
                return False
            return True

        tf = rewrites.get("teen_friendly")
        pf = rewrites.get("parent_friendly")
        if isinstance(tf, str) and _check_msg_constraints(tf):
            scores["rewrites_teen_friendly_constraints"] = 1.0
        if isinstance(pf, str) and _check_msg_constraints(pf):
            scores["rewrites_parent_friendly_constraints"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()