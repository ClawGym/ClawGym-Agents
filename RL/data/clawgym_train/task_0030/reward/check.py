import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any


ALLOWED_RAW_EXTS = ["xml", "rss", "atom", "xml.gz", "html"]


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _parse_iso_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    try:
        # Handle trailing Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        # If only date part
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s, "%Y-%m-%d")
        # Try fromisoformat
        try:
            return datetime.fromisoformat(s)
        except Exception:
            pass
        # Common patterns
        for fmt in [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S.%f",
        ]:
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
    except Exception:
        return None
    return None


def _find_download_file(workspace: Path, base_name: str) -> Optional[Path]:
    raw_dir = workspace / "downloads" / "raw"
    if not raw_dir.exists():
        return None
    candidates: List[Path] = []
    for ext in ALLOWED_RAW_EXTS:
        p = raw_dir / f"{base_name}.{ext}"
        if p.exists() and p.is_file():
            candidates.append(p)
    if not candidates:
        # Also allow unexpected case where extension case varies
        for p in raw_dir.iterdir() if raw_dir.exists() else []:
            if p.is_file() and p.name.startswith(base_name + "."):
                # check allowed suffix regardless of case
                for ext in ALLOWED_RAW_EXTS:
                    if p.name.lower().endswith("." + ext):
                        candidates.append(p)
                        break
    if not candidates:
        return None
    # Choose deterministic: sort by name
    candidates.sort(key=lambda x: x.name)
    return candidates[0]


def _is_nonempty_file(path: Optional[Path]) -> bool:
    try:
        return path is not None and path.exists() and path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def _check_header_exact(header: Optional[List[str]], expected: List[str]) -> bool:
    if header is None:
        return False
    return header == expected


def _to_int_safe(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _normalize_str(s: Optional[str]) -> str:
    return (s or "").strip()


def _contains_theme(matched_themes_cell: str, theme: str) -> bool:
    # Case-insensitive substring check; robust to lists/CSV/JSON string forms.
    return theme.lower() in (matched_themes_cell or "").lower()


def _sorted_candidates(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    def keyfunc(r: Dict[str, str]):
        d = _parse_iso_date(_normalize_str(r.get("published_date", "")))
        # Missing dates should be treated as oldest; use very early time
        d_key = d if d is not None else datetime.min
        hits = _to_int_safe(_normalize_str(r.get("keyword_hits", ""))) or 0
        title = _normalize_str(r.get("title", ""))
        # Sort: date desc, hits desc, title asc
        return (-int(d_key.timestamp()) if d is not None else int(datetime.min.timestamp()), -hits, title)
    # Since datetime.min.timestamp() may raise OSError on some systems, handle separately
    def safer_key(r: Dict[str, str]):
        d = _parse_iso_date(_normalize_str(r.get("published_date", "")))
        if d is None:
            d_ts = float("-inf")
        else:
            try:
                d_ts = d.timestamp()
            except Exception:
                d_ts = float("-inf")
        hits = _to_int_safe(_normalize_str(r.get("keyword_hits", ""))) or 0
        title = _normalize_str(r.get("title", ""))
        return (-d_ts, -hits, title)
    return sorted(rows, key=safer_key)


def _get_today_date_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "downloads_app_raw_present": 0.0,
        "downloads_pid_raw_present": 0.0,
        "news_candidates_columns": 0.0,
        "news_candidates_ranks_and_sort": 0.0,
        "news_candidates_theme_hits_valid": 0.0,
        "top_by_theme_columns": 0.0,
        "top_by_theme_selection": 0.0,
        "messages_rewritten_columns": 0.0,
        "messages_rewritten_coverage_and_limits": 0.0,
        "content_calendar_columns_and_rows": 0.0,
        "content_calendar_dates_consecutive_from_today": 0.0,
        "content_calendar_platform_allocation": 0.0,
        "content_calendar_post_text_and_tone_valid": 0.0,
        "content_calendar_source_links_valid": 0.0,
        "fetch_report_quality": 0.0,
        "readme_coverage": 0.0,
    }

    # 1) Downloads presence checks
    app_path = _find_download_file(workspace, "app_feed")
    pid_path = _find_download_file(workspace, "pid_feed")
    if _is_nonempty_file(app_path):
        # ensure allowed extension
        name = app_path.name.lower()
        if any(name.endswith("." + ext) for ext in ALLOWED_RAW_EXTS):
            scores["downloads_app_raw_present"] = 1.0
    if _is_nonempty_file(pid_path):
        name = pid_path.name.lower()
        if any(name.endswith("." + ext) for ext in ALLOWED_RAW_EXTS):
            scores["downloads_pid_raw_present"] = 1.0

    # Load inputs used for validation
    input_dir = workspace / "input"
    themes_csv_path = input_dir / "content_themes.csv"
    msg_csv_path = input_dir / "message_drafts.csv"
    platforms_csv_path = input_dir / "platforms.csv"
    theme_keywords_path = input_dir / "theme_keywords.json"

    # Parse inputs (gracefully handle missing)
    _, themes_rows = _read_csv_safe(themes_csv_path)
    _, msg_rows = _read_csv_safe(msg_csv_path)
    _, platforms_rows = _read_csv_safe(platforms_csv_path)
    theme_keywords = _load_json_safe(theme_keywords_path)

    themes_list: List[str] = []
    if themes_rows is not None:
        for r in themes_rows:
            tname = _normalize_str(r.get("theme_name", ""))
            if tname:
                themes_list.append(tname)

    # 2) news_candidates.csv checks
    news_candidates_path = workspace / "output" / "news_candidates.csv"
    expected_news_cols = [
        "source_domain",
        "title",
        "link",
        "published_date",
        "summary_or_snippet",
        "matched_themes",
        "keyword_hits",
        "rank_overall",
    ]
    news_header, news_rows = _read_csv_safe(news_candidates_path)
    if _check_header_exact(news_header, expected_news_cols):
        scores["news_candidates_columns"] = 1.0

        # theme_hits_valid: if there are rows, ensure matched_themes non-empty and keyword_hits >= 1
        theme_hits_ok = True
        if news_rows is not None:
            for r in news_rows:
                mt = _normalize_str(r.get("matched_themes", ""))
                hits = _to_int_safe(_normalize_str(r.get("keyword_hits", "")))
                # For filtered set, all should match at least one theme and hits >= 1
                if len(news_rows) > 0:
                    if not mt:
                        theme_hits_ok = False
                        break
                    if hits is None or hits < 1:
                        theme_hits_ok = False
                        break
        else:
            theme_hits_ok = False
        if theme_hits_ok:
            scores["news_candidates_theme_hits_valid"] = 1.0

        # ranks_and_sort: ranks start at 1 and increment by 1; file sorted by described rules and matches rank
        sort_ok = True
        rank_ok = True
        if news_rows is not None:
            if len(news_rows) == 0:
                # Empty allowed; keep both ok
                sort_ok = True
                rank_ok = True
            else:
                # Ranks incremental
                ranks = []
                for r in news_rows:
                    ro = _to_int_safe(_normalize_str(r.get("rank_overall", "")))
                    if ro is None:
                        rank_ok = False
                        break
                    ranks.append(ro)
                if rank_ok:
                    # ranks should be 1..n and strictly increasing by 1 in file order
                    n = len(ranks)
                    if ranks != list(range(1, n + 1)):
                        rank_ok = False
                # Sorting correctness
                # Compute expected sort
                expected_sorted = _sorted_candidates(news_rows)
                # Compare titles+links order between file and expected
                file_order = [(r.get("title", ""), r.get("link", "")) for r in news_rows]
                expected_order = [(r.get("title", ""), r.get("link", "")) for r in expected_sorted]
                if file_order != expected_order:
                    sort_ok = False
                # Also check that assigned ranks correspond to position in expected sort
                if rank_ok:
                    for idx, r in enumerate(expected_sorted, start=1):
                        ro = _to_int_safe(_normalize_str(r.get("rank_overall", "")))
                        if ro != idx:
                            rank_ok = False
                            break
        else:
            sort_ok = False
            rank_ok = False

        if sort_ok and rank_ok:
            scores["news_candidates_ranks_and_sort"] = 1.0

    # 3) top_by_theme.csv checks
    top_by_theme_path = workspace / "output" / "top_by_theme.csv"
    expected_top_cols = [
        "theme",
        "source_domain",
        "title",
        "link",
        "published_date",
        "keyword_hits",
        "rank_overall",
    ]
    top_header, top_rows = _read_csv_safe(top_by_theme_path)
    if _check_header_exact(top_header, expected_top_cols):
        scores["top_by_theme_columns"] = 1.0

        sel_ok = True
        if top_rows is None:
            sel_ok = False
        else:
            # Validate each row theme is in themes_list
            if themes_list:
                for r in top_rows:
                    th = _normalize_str(r.get("theme", ""))
                    if th not in themes_list:
                        sel_ok = False
                        break
            # Validate links are from candidates and top 3 per theme by rank_overall
            if sel_ok:
                news_links_set = set()
                rank_map: Dict[Tuple[str, str], int] = {}
                if news_rows is not None:
                    for nr in news_rows:
                        link = _normalize_str(nr.get("link", ""))
                        news_links_set.add(link)
                        ro = _to_int_safe(_normalize_str(nr.get("rank_overall", ""))) or 10**9
                        title = _normalize_str(nr.get("title", ""))
                        rank_map[(title, link)] = ro
                # Build expected top 3 per theme based on candidates whose matched_themes includes that theme
                if news_rows is not None and themes_list:
                    # For each theme, gather and sort by rank_overall asc
                    expected_for_theme: Dict[str, List[Tuple[str, str, int]]] = {}
                    for theme in themes_list:
                        items: List[Tuple[str, str, int]] = []
                        for nr in news_rows:
                            if _contains_theme(_normalize_str(nr.get("matched_themes", "")), theme):
                                title = _normalize_str(nr.get("title", ""))
                                link = _normalize_str(nr.get("link", ""))
                                ro = _to_int_safe(_normalize_str(nr.get("rank_overall", ""))) or 10**9
                                items.append((title, link, ro))
                        items.sort(key=lambda x: x[2])
                        expected_for_theme[theme] = items[:3]
                    # Validate top_by_theme rows do not exceed 3 per theme and are sorted by rank_overall asc
                    rows_by_theme: Dict[str, List[Dict[str, str]]] = {}
                    for r in top_rows:
                        th = _normalize_str(r.get("theme", ""))
                        rows_by_theme.setdefault(th, []).append(r)
                        # Each link should be in candidates (if candidates exist)
                        if news_rows is not None and len(news_rows) > 0:
                            if _normalize_str(r.get("link", "")) not in news_links_set:
                                sel_ok = False
                                break
                    if sel_ok:
                        for th, rows_th in rows_by_theme.items():
                            if len(rows_th) > 3:
                                sel_ok = False
                                break
                            # Sorted by rank_overall asc and matches expected top
                            got_pairs = [(_normalize_str(r.get("title", "")), _normalize_str(r.get("link", ""))) for r in rows_th]
                            exp_pairs = [(t, l) for (t, l, _) in expected_for_theme.get(th, [])]
                            # If there are fewer candidates than 3, exp_pairs may be shorter
                            if got_pairs != exp_pairs:
                                sel_ok = False
                                break
        if sel_ok:
            scores["top_by_theme_selection"] = 1.0

    # 4) messages_rewritten.csv checks
    msg_out_path = workspace / "output" / "messages_rewritten.csv"
    expected_msg_cols = ["id", "original_draft", "rewrite_neutral", "rewrite_friendly"]
    msg_out_header, msg_out_rows = _read_csv_safe(msg_out_path)
    if _check_header_exact(msg_out_header, expected_msg_cols):
        scores["messages_rewritten_columns"] = 1.0

        cov_ok = True
        if msg_rows is None or msg_out_rows is None:
            cov_ok = False
        else:
            # Map input drafts by id->text
            in_map: Dict[str, str] = {}
            for r in msg_rows:
                rid = _normalize_str(r.get("id", ""))
                txt = _normalize_str(r.get("draft_text", ""))
                if rid:
                    in_map[rid] = txt
            out_map: Dict[str, Dict[str, str]] = {}
            for r in msg_out_rows:
                rid = _normalize_str(r.get("id", ""))
                out_map[rid] = r
            # Validate each input id present with rewrites <= 240 chars and non-empty, different from original
            for rid, orig in in_map.items():
                if rid not in out_map:
                    cov_ok = False
                    break
                row = out_map[rid]
                rn = _normalize_str(row.get("rewrite_neutral", ""))
                rf = _normalize_str(row.get("rewrite_friendly", ""))
                od = _normalize_str(row.get("original_draft", ""))
                if not rn or not rf:
                    cov_ok = False
                    break
                if len(rn) > 240 or len(rf) > 240:
                    cov_ok = False
                    break
                if od != orig:
                    # original_draft should mirror input draft_text
                    # Minor whitespace differences allowed
                    if od.strip() != orig.strip():
                        cov_ok = False
                        break
                # Should be rewritten: different from original_draft
                if rn.strip() == od.strip() or rf.strip() == od.strip():
                    cov_ok = False
                    break
        if cov_ok:
            scores["messages_rewritten_coverage_and_limits"] = 1.0

    # 5) content_calendar.csv checks
    calendar_path = workspace / "output" / "content_calendar.csv"
    expected_cal_cols = ["date", "platform", "post_text", "source_link", "theme", "tone", "utm_tag"]
    cal_header, cal_rows = _read_csv_safe(calendar_path)
    if _check_header_exact(cal_header, expected_cal_cols):
        # Check exactly 14 rows
        if cal_rows is not None and len(cal_rows) == 14:
            scores["content_calendar_columns_and_rows"] = 1.0

        # Dates consecutive from today
        dates_ok = False
        if cal_rows is not None and len(cal_rows) == 14:
            # Collect unique dates
            unique_dates = sorted(set(_normalize_str(r.get("date", "")) for r in cal_rows))
            # All dates should be valid YYYY-MM-DD
            try:
                parsed_dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in unique_dates]
                # Should be 7 consecutive days starting today
                today = datetime.utcnow().date()
                expected = [today + timedelta(days=i) for i in range(7)]
                if parsed_dates == expected:
                    # Check each date has exactly 2 rows
                    counts: Dict[str, int] = {}
                    for r in cal_rows:
                        d = _normalize_str(r.get("date", ""))
                        counts[d] = counts.get(d, 0) + 1
                    if all(counts.get(d.strftime("%Y-%m-%d"), 0) == 2 for d in expected):
                        dates_ok = True
            except Exception:
                dates_ok = False
        if dates_ok:
            scores["content_calendar_dates_consecutive_from_today"] = 1.0

        # Platform allocation per input/platforms.csv: 1 X and 1 Facebook per day
        platform_ok = False
        if cal_rows is not None and len(cal_rows) == 14:
            day_platforms: Dict[str, List[str]] = {}
            for r in cal_rows:
                d = _normalize_str(r.get("date", ""))
                p = _normalize_str(r.get("platform", ""))
                day_platforms.setdefault(d, []).append(p)
            # Determine expected platforms and counts from platforms.csv
            expected_plat_counts: Dict[str, int] = {}
            if platforms_rows is not None:
                for pr in platforms_rows:
                    p = _normalize_str(pr.get("platform", ""))
                    c = _to_int_safe(_normalize_str(pr.get("daily_slots", ""))) or 0
                    expected_plat_counts[p] = c
            # Must be exactly 2 per day: 1 X and 1 Facebook
            platform_ok = True
            for d, plist in day_platforms.items():
                counts: Dict[str, int] = {}
                for p in plist:
                    counts[p] = counts.get(p, 0) + 1
                # Check matches expected_plat_counts
                for p, c in expected_plat_counts.items():
                    if counts.get(p, 0) != c:
                        platform_ok = False
                        break
                # No extra platforms
                if set(counts.keys()) != set(expected_plat_counts.keys()):
                    platform_ok = False
                if not platform_ok:
                    break
        if platform_ok:
            scores["content_calendar_platform_allocation"] = 1.0

        # Post text and tone validity, utm_tag
        post_tone_ok = False
        if cal_rows is not None and msg_out_rows is not None:
            # Build mapping from rewrite text to tone type
            neutral_set = set(_normalize_str(r.get("rewrite_neutral", "")) for r in msg_out_rows)
            friendly_set = set(_normalize_str(r.get("rewrite_friendly", "")) for r in msg_out_rows)
            # Validate theme values and utm_tag
            theme_set = set(themes_list)
            post_tone_ok = True
            for r in cal_rows:
                post_text = _normalize_str(r.get("post_text", ""))
                tone = _normalize_str(r.get("tone", ""))
                utm = _normalize_str(r.get("utm_tag", ""))
                theme_val = _normalize_str(r.get("theme", ""))
                if utm != "unity_campaign":
                    post_tone_ok = False
                    break
                # theme must be one of themes
                if theme_set and theme_val not in theme_set:
                    post_tone_ok = False
                    break
                # post_text must be one of the rewritten variants and tone must match
                if post_text in neutral_set:
                    if tone != "neutral":
                        post_tone_ok = False
                        break
                elif post_text in friendly_set:
                    if tone != "friendly":
                        post_tone_ok = False
                        break
                else:
                    post_tone_ok = False
                    break
        if post_tone_ok:
            scores["content_calendar_post_text_and_tone_valid"] = 1.0

        # Source links validity
        src_links_ok = False
        if cal_rows is not None:
            if news_rows is None:
                # Can't validate without candidates; fail
                src_links_ok = False
            else:
                cand_links = set(_normalize_str(r.get("link", "")) for r in news_rows)
                if len(news_rows) == 0:
                    # All source_link should be blank
                    src_links_ok = all(_normalize_str(r.get("source_link", "")) == "" for r in cal_rows)
                else:
                    # All source_link must be non-empty and from candidates
                    src_links_ok = True
                    for r in cal_rows:
                        sl = _normalize_str(r.get("source_link", ""))
                        if not sl or sl not in cand_links:
                            src_links_ok = False
                            break
        if src_links_ok:
            scores["content_calendar_source_links_valid"] = 1.0

    # 6) fetch_report.txt quality
    fetch_report_path = workspace / "logs" / "fetch_report.txt"
    report_text = _read_text_safe(fetch_report_path)
    if report_text is not None:
        # Must mention both sources (app and pid)
        mentions_app = ("app.com.pk" in report_text.lower()) or ("app" in report_text.lower())
        mentions_pid = ("pid.gov.pk" in report_text.lower()) or ("pid" in report_text.lower())
        mentions_method = any(k in report_text.lower() for k in ["curl", "wget", "requests"])
        mentions_resource_type = any(k in report_text.lower() for k in ["feed", "sitemap"])
        mentions_status_or_exception = any(k in report_text.lower() for k in ["status", "http", "exception", "error", "200", "403", "404"])
        if mentions_app and mentions_pid and mentions_method and mentions_resource_type and mentions_status_or_exception:
            scores["fetch_report_quality"] = 1.0

    # 7) report/README.md coverage
    readme_path = workspace / "report" / "README.md"
    readme_text = _read_text_safe(readme_path)
    if readme_text is not None:
        lower = readme_text.lower()
        # sources and resource types used
        sources_ok = (("app.com.pk" in lower or "associated press of pakistan" in lower or "app" in lower) and
                      ("pid.gov.pk" in lower or "press information department" in lower or "pid" in lower))
        types_ok = ("feed" in lower or "sitemap" in lower)
        # numbers for parsed and matched
        parsed_ok = ("parsed" in lower and re.search(r"\b\d+\b", lower) is not None)
        matched_ok = ("matched" in lower and re.search(r"\b\d+\b", lower) is not None)
        # sorting and ranking rules mention
        sorting_ok = (("sort" in lower or "sorted" in lower or "sorting" in lower) and ("rank" in lower or "ranking" in lower))
        # character-limit check and number of calendar rows
        char_ok = (("character" in lower or "characters" in lower) and ("240" in lower or "two hundred forty" in lower))
        calendar_rows_ok = (("calendar" in lower) and (re.search(r"\b14\b", lower) is not None or "fourteen" in lower))
        if sources_ok and types_ok and parsed_ok and matched_ok and sorting_ok and char_ok and calendar_rows_ok:
            scores["readme_coverage"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()