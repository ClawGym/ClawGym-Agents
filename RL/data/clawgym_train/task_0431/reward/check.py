import csv
import json
import re
import sys
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _write_debug(msg: str) -> None:
    # No-op placeholder; keep for potential future diagnostics if needed.
    return


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _day_abbrev(dt: date) -> str:
    # Monday=0 ... Sunday=6
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.weekday()]


def _time_slot_valid(slot: str) -> bool:
    return slot in {"morning", "afternoon", "evening"}


def _nearly_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _compute_engagement_summaries(past_posts_path: Path) -> Optional[Dict[str, Any]]:
    rows = _read_csv_dicts(past_posts_path)
    if rows is None:
        return None
    required_cols = {"date", "time_slot", "theme", "reach", "likes", "comments", "shares"}
    if not rows:
        # Empty file - still must validate headers; if headers present but no rows, summaries are empty
        # We need to verify headers; csv.DictReader without rows still provides fieldnames
        try:
            with past_posts_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if set(reader.fieldnames or []) != required_cols:
                    return None
        except Exception:
            return None
        return {"by_day_time": {}, "by_theme": {}}

    # Check columns presence in first row
    if set(rows[0].keys()) != required_cols:
        return None

    by_day_time: Dict[Tuple[str, str], Dict[str, float]] = {}
    by_theme: Dict[str, Dict[str, float]] = {}

    for r in rows:
        ds = r.get("date", "").strip()
        dt = _parse_iso_date(ds)
        if dt is None:
            return None
        day = _day_abbrev(dt)
        slot = r.get("time_slot", "").strip()
        if not _time_slot_valid(slot):
            return None
        theme = r.get("theme", "").strip()
        likes = _safe_int(r.get("likes", "").strip())
        comments = _safe_int(r.get("comments", "").strip())
        shares = _safe_int(r.get("shares", "").strip())
        if likes is None or comments is None or shares is None:
            return None
        total = likes + comments + shares

        key_dt = (day, slot)
        if key_dt not in by_day_time:
            by_day_time[key_dt] = {"sum": 0.0, "count": 0}
        by_day_time[key_dt]["sum"] += float(total)
        by_day_time[key_dt]["count"] += 1

        if theme not in by_theme:
            by_theme[theme] = {"sum": 0.0, "count": 0}
        by_theme[theme]["sum"] += float(total)
        by_theme[theme]["count"] += 1

    # Produce averages
    by_day_time_avg: Dict[Tuple[str, str], Dict[str, float]] = {}
    for k, v in by_day_time.items():
        c = v["count"]
        s = v["sum"]
        avg = s / c if c else 0.0
        by_day_time_avg[k] = {"avg": avg, "count": c}

    by_theme_avg: Dict[str, Dict[str, float]] = {}
    for k, v in by_theme.items():
        c = v["count"]
        s = v["sum"]
        avg = s / c if c else 0.0
        by_theme_avg[k] = {"avg": avg, "count": c}

    return {"by_day_time": by_day_time_avg, "by_theme": by_theme_avg}


def _load_avg_by_day_time(path: Path) -> Optional[Dict[Tuple[str, str], Tuple[float, int]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    # Validate header order and names strictly
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return None
    expected_header = ["day_of_week", "time_slot", "avg_total_engagement", "posts_count"]
    if header != expected_header:
        return None

    result: Dict[Tuple[str, str], Tuple[float, int]] = {}
    for r in rows:
        day = r.get("day_of_week", "").strip()
        slot = r.get("time_slot", "").strip()
        avg_s = r.get("avg_total_engagement", "").strip()
        cnt_s = r.get("posts_count", "").strip()

        if day not in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}:
            return None
        if not _time_slot_valid(slot):
            return None
        try:
            avg = float(avg_s)
        except Exception:
            return None
        cnt = _safe_int(cnt_s)
        if cnt is None:
            return None
        key = (day, slot)
        if key in result:
            # Duplicate key not allowed
            return None
        result[key] = (avg, cnt)
    return result


def _load_avg_by_theme(path: Path) -> Optional[Dict[str, Tuple[float, int]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return None
    expected_header = ["theme", "avg_total_engagement", "posts_count"]
    if header != expected_header:
        return None

    result: Dict[str, Tuple[float, int]] = {}
    for r in rows:
        theme = r.get("theme", "").strip()
        avg_s = r.get("avg_total_engagement", "").strip()
        cnt_s = r.get("posts_count", "").strip()
        try:
            avg = float(avg_s)
        except Exception:
            return None
        cnt = _safe_int(cnt_s)
        if cnt is None:
            return None
        if theme in result:
            return None
        result[theme] = (avg, cnt)
    return result


def _count_sentences(text: str) -> int:
    # Count sentences by splitting on ., !, ? and counting non-empty segments
    # Normalize ellipsis and repeated punctuation
    clean = re.sub(r"[\"'\n]+", " ", text)
    parts = re.split(r"[.!?]+", clean)
    count = sum(1 for p in parts if p.strip())
    return count


def _contains_slang_or_pop(text: str) -> bool:
    # Case-insensitive; check a list of slang/pop-culture terms including K-pop
    patterns = [
        r"\bomg\b",
        r"\blit\b",
        r"\bvibes?\b",
        r"\bepic\b",
        r"\bkinda\b",
        r"\blol\b",
        r"\bbtw\b",
        r"\btbh\b",
        r"\bikr\b",
        r"\bidk\b",
        r"\bbae\b",
        r"\bfam\b",
        r"\bfire\b",
        r"\bdope\b",
        r"\byeet\b",
        r"\bstan\b",
        r"\bswag\b",
        r"\bfomo\b",
        r"\byo\b",
        r"\blmao\b",
        r"\brofl\b",
        r"\byolo\b",
        r"k-?pop",
    ]
    lower = text.lower()
    for pat in patterns:
        if re.search(pat, lower, flags=re.IGNORECASE):
            return True
    return False


def _parse_reference_monday(path: Path) -> Optional[date]:
    s = _read_text(path)
    if s is None:
        return None
    return _parse_iso_date(s.strip())


def _week_dates_from_monday(monday: date) -> Dict[str, date]:
    # Returns mapping from day abbrev to date in that reference week
    mapping: Dict[str, date] = {}
    for i in range(7):
        d = monday + timedelta(days=i)
        mapping[_day_abbrev(d)] = d
    return mapping


def _load_content_calendar(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return None
    expected_header = ["date", "day_of_week", "time_slot", "theme", "caption_file", "channel"]
    if header != expected_header:
        return None
    return rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "avg_by_day_time_exists": 0.0,
        "avg_by_day_time_structure": 0.0,
        "avg_by_day_time_values": 0.0,
        "avg_by_theme_exists": 0.0,
        "avg_by_theme_structure": 0.0,
        "avg_by_theme_values": 0.0,
        "captions_exist": 0.0,
        "caption1_sentence_count": 0.0,
        "caption2_sentence_count": 0.0,
        "captions_no_slang": 0.0,
        "content_calendar_exists": 0.0,
        "content_calendar_structure": 0.0,
        "content_calendar_two_posts": 0.0,
        "content_calendar_dates_within_week": 0.0,
        "content_calendar_day_time_matches_top_pairs": 0.0,
        "content_calendar_themes_assignment": 0.0,
        "content_calendar_captions_and_channels": 0.0,
        "email_long_exists": 0.0,
        "email_long_word_count": 0.0,
        "email_long_includes_required_info": 0.0,
        "email_long_no_slang": 0.0,
        "email_short_exists": 0.0,
        "email_short_length": 0.0,
        "email_short_includes_required_info": 0.0,
        "email_short_no_slang": 0.0,
    }

    # Paths
    input_posts = workspace / "input" / "past_posts.csv"
    input_reference = workspace / "input" / "reference_week.txt"
    out_avg_day_time = workspace / "output" / "avg_by_day_time.csv"
    out_avg_theme = workspace / "output" / "avg_by_theme.csv"
    out_caption1 = workspace / "output" / "rewritten_captions" / "caption1.txt"
    out_caption2 = workspace / "output" / "rewritten_captions" / "caption2.txt"
    out_calendar = workspace / "output" / "content_calendar.csv"
    out_email_long = workspace / "output" / "email_long.txt"
    out_email_short = workspace / "output" / "email_short_sms.txt"

    # Compute ground truth summaries from input
    computed = _compute_engagement_summaries(input_posts)
    # Load outputs
    loaded_day_time: Optional[Dict[Tuple[str, str], Tuple[float, int]]] = None
    loaded_theme: Optional[Dict[str, Tuple[float, int]]] = None

    # Check avg_by_day_time.csv
    if out_avg_day_time.exists():
        scores["avg_by_day_time_exists"] = 1.0
        loaded_day_time = _load_avg_by_day_time(out_avg_day_time)
        if loaded_day_time is not None:
            scores["avg_by_day_time_structure"] = 1.0
            if computed is not None:
                truth = computed["by_day_time"]  # Dict[(day,slot)] -> {"avg":float,"count":int}
                # Keys must match exactly
                if set(loaded_day_time.keys()) == set(truth.keys()):
                    # Check values
                    all_match = True
                    for k, (avg_out, cnt_out) in loaded_day_time.items():
                        avg_true = truth[k]["avg"]
                        cnt_true = int(truth[k]["count"])
                        if cnt_true != cnt_out or not _nearly_equal(avg_true, avg_out, tol=1e-6):
                            all_match = False
                            break
                    if all_match:
                        scores["avg_by_day_time_values"] = 1.0
                else:
                    scores["avg_by_day_time_values"] = 0.0
            else:
                scores["avg_by_day_time_values"] = 0.0
        else:
            scores["avg_by_day_time_structure"] = 0.0
            scores["avg_by_day_time_values"] = 0.0
    else:
        scores["avg_by_day_time_exists"] = 0.0

    # Check avg_by_theme.csv
    if out_avg_theme.exists():
        scores["avg_by_theme_exists"] = 1.0
        loaded_theme = _load_avg_by_theme(out_avg_theme)
        if loaded_theme is not None:
            scores["avg_by_theme_structure"] = 1.0
            if computed is not None:
                truth_t = computed["by_theme"]
                if set(loaded_theme.keys()) == set(truth_t.keys()):
                    all_match = True
                    for theme, (avg_out, cnt_out) in loaded_theme.items():
                        avg_true = truth_t[theme]["avg"]
                        cnt_true = int(truth_t[theme]["count"])
                        if cnt_true != cnt_out or not _nearly_equal(avg_true, avg_out, tol=1e-6):
                            all_match = False
                            break
                    if all_match:
                        scores["avg_by_theme_values"] = 1.0
                else:
                    scores["avg_by_theme_values"] = 0.0
            else:
                scores["avg_by_theme_values"] = 0.0
        else:
            scores["avg_by_theme_structure"] = 0.0
            scores["avg_by_theme_values"] = 0.0
    else:
        scores["avg_by_theme_exists"] = 0.0

    # Captions checks
    cap1_txt = _read_text(out_caption1) if out_caption1.exists() else None
    cap2_txt = _read_text(out_caption2) if out_caption2.exists() else None
    if cap1_txt is not None and cap2_txt is not None:
        scores["captions_exist"] = 1.0
        # sentence counts
        s1 = _count_sentences(cap1_txt)
        s2 = _count_sentences(cap2_txt)
        if 1 <= s1 <= 2:
            scores["caption1_sentence_count"] = 1.0
        if 1 <= s2 <= 2:
            scores["caption2_sentence_count"] = 1.0
        # slang/pop check
        no_slang = (not _contains_slang_or_pop(cap1_txt)) and (not _contains_slang_or_pop(cap2_txt))
        if no_slang:
            scores["captions_no_slang"] = 1.0
    else:
        # Missing captions: leave zeros as initialized
        pass

    # Content calendar checks
    calendar_rows = _load_content_calendar(out_calendar) if out_calendar.exists() else None
    if out_calendar.exists():
        scores["content_calendar_exists"] = 1.0
        if calendar_rows is not None:
            scores["content_calendar_structure"] = 1.0
            # Must be exactly two rows
            if len(calendar_rows) == 2:
                scores["content_calendar_two_posts"] = 1.0
            # Reference week
            monday = _parse_reference_monday(input_reference)
            if monday is not None:
                week_map = _week_dates_from_monday(monday)
                # Validate dates within week and day_of_week matches
                within_week_ok = True
                parsed_rows: List[Dict[str, Any]] = []
                for r in calendar_rows:
                    ds = r.get("date", "").strip()
                    day_of_week = r.get("day_of_week", "").strip()
                    time_slot = r.get("time_slot", "").strip()
                    theme = r.get("theme", "").strip()
                    caption_file = r.get("caption_file", "").strip()
                    channel = r.get("channel", "").strip()
                    d = _parse_iso_date(ds)
                    if d is None:
                        within_week_ok = False
                        break
                    # Date within Monday..Sunday
                    if not (monday <= d <= monday + timedelta(days=6)):
                        within_week_ok = False
                        break
                    # Day abbreviation matches actual
                    if _day_abbrev(d) != day_of_week:
                        within_week_ok = False
                        break
                    # Time slot validity
                    if not _time_slot_valid(time_slot):
                        within_week_ok = False
                        break
                    parsed_rows.append({
                        "date": d,
                        "day_of_week": day_of_week,
                        "time_slot": time_slot,
                        "theme": theme,
                        "caption_file": caption_file,
                        "channel": channel,
                    })
                if within_week_ok:
                    scores["content_calendar_dates_within_week"] = 1.0

                # Compare top day/time pairs and themes if computed summaries available
                if computed is not None and within_week_ok:
                    # Determine top two day_time pairs by average, deterministic tie-break by day index then time slot order
                    daytime_items = list(computed["by_day_time"].items())  # [((day,slot), {"avg":..,"count":..}), ...]
                    day_order = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
                    time_order = {"morning": 0, "afternoon": 1, "evening": 2}
                    daytime_items.sort(key=lambda kv: (-kv[1]["avg"], day_order[kv[0][0]], time_order[kv[0][1]]))
                    top_pairs = [daytime_items[0][0], daytime_items[1][0]] if len(daytime_items) >= 2 else [kv[0] for kv in daytime_items]

                    # Set of pairs in calendar
                    cal_pairs = [(r["day_of_week"], r["time_slot"]) for r in parsed_rows]
                    if len(top_pairs) == 2 and set(cal_pairs) == set(top_pairs):
                        scores["content_calendar_day_time_matches_top_pairs"] = 1.0

                    # Themes: top two by avg, deterministic tie-break by theme name
                    theme_items = list(computed["by_theme"].items())  # [(theme, {"avg":..,"count":..}), ...]
                    theme_items.sort(key=lambda kv: (-kv[1]["avg"], kv[0]))
                    top_themes = [theme_items[0][0], theme_items[1][0]] if len(theme_items) >= 2 else [kv[0] for kv in theme_items]

                    # Assignments: top theme to the post with the highest-ranked day/time pair among the two
                    # Identify which parsed_row corresponds to top_pairs[0] and top_pairs[1]
                    pair_to_row = { (r["day_of_week"], r["time_slot"]): r for r in parsed_rows }
                    theme_ok = True
                    if len(top_pairs) >= 1:
                        r1 = pair_to_row.get(top_pairs[0])
                        if r1 is None or r1["theme"] != (top_themes[0] if len(top_themes) >= 1 else r1["theme"]):
                            theme_ok = False
                    if len(top_pairs) >= 2:
                        r2 = pair_to_row.get(top_pairs[1])
                        if r2 is None or r2["theme"] != (top_themes[1] if len(top_themes) >= 2 else r2["theme"]):
                            theme_ok = False
                    if theme_ok and len(parsed_rows) == 2:
                        scores["content_calendar_themes_assignment"] = 1.0

                    # Captions and channels alternating: first scheduled post (top pair) -> caption1 + Facebook; second -> caption2 + Instagram
                    captions_ok = True
                    if len(top_pairs) >= 1:
                        r1 = pair_to_row.get(top_pairs[0])
                        if r1 is None or r1["caption_file"] != "output/rewritten_captions/caption1.txt" or r1["channel"] != "Facebook":
                            captions_ok = False
                    if len(top_pairs) >= 2:
                        r2 = pair_to_row.get(top_pairs[1])
                        if r2 is None or r2["caption_file"] != "output/rewritten_captions/caption2.txt" or r2["channel"] != "Instagram":
                            captions_ok = False
                    if captions_ok and len(parsed_rows) == 2:
                        scores["content_calendar_captions_and_channels"] = 1.0
        else:
            scores["content_calendar_structure"] = 0.0
    else:
        scores["content_calendar_exists"] = 0.0

    # Email long checks
    email_long_txt = _read_text(out_email_long) if out_email_long.exists() else None
    if out_email_long.exists():
        scores["email_long_exists"] = 1.0
        if email_long_txt is not None:
            words = [w for w in re.split(r"\s+", email_long_txt.strip()) if w]
            if 150 <= len(words) <= 200:
                scores["email_long_word_count"] = 1.0
            # Required info: date (Saturday of reference week), time 10:00–14:00 (allow hyphen or en dash), location
            monday = _parse_reference_monday(input_reference)
            date_ok = False
            time_ok = False
            loc_ok = False
            if monday is not None:
                saturday = monday + timedelta(days=5)
                saturday_iso = saturday.strftime("%Y-%m-%d")
                if saturday_iso in email_long_txt:
                    date_ok = True
            # Time pattern
            if re.search(r"10:00\s*[–-]\s*14:00", email_long_txt):
                time_ok = True
            # Location exact phrase case-insensitive
            if re.search(r"Lincoln Elementary parking lot", email_long_txt, flags=re.IGNORECASE):
                loc_ok = True
            if date_ok and time_ok and loc_ok:
                scores["email_long_includes_required_info"] = 1.0
            # Slang/pop check
            if not _contains_slang_or_pop(email_long_txt):
                scores["email_long_no_slang"] = 1.0
    else:
        scores["email_long_exists"] = 0.0

    # Email short checks
    email_short_txt = _read_text(out_email_short) if out_email_short.exists() else None
    if out_email_short.exists():
        scores["email_short_exists"] = 1.0
        if email_short_txt is not None:
            if len(email_short_txt.strip()) <= 160:
                scores["email_short_length"] = 1.0
            # Required info same as long
            monday = _parse_reference_monday(input_reference)
            date_ok = False
            time_ok = False
            loc_ok = False
            if monday is not None:
                saturday = monday + timedelta(days=5)
                saturday_iso = saturday.strftime("%Y-%m-%d")
                if saturday_iso in email_short_txt:
                    date_ok = True
            if re.search(r"10:00\s*[–-]\s*14:00", email_short_txt):
                time_ok = True
            if re.search(r"Lincoln Elementary parking lot", email_short_txt, flags=re.IGNORECASE):
                loc_ok = True
            if date_ok and time_ok and loc_ok:
                scores["email_short_includes_required_info"] = 1.0
            if not _contains_slang_or_pop(email_short_txt):
                scores["email_short_no_slang"] = 1.0
    else:
        scores["email_short_exists"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()