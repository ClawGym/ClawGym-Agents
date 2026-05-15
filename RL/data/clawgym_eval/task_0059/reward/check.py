import csv
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import runpy


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _parse_marketing_yaml(yaml_path: Path) -> dict:
    text = _read_text(yaml_path)
    if not text:
        return {}
    cfg = {}
    # simple top-level scalars
    m = re.search(r'^\s*start_date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$', text, re.M)
    if m:
        cfg["start_date"] = m.group(1)
    m = re.search(r'^\s*weeks:\s*(\d+)\s*$', text, re.M)
    if m:
        try:
            cfg["weeks"] = int(m.group(1))
        except Exception:
            pass
    # lists
    def parse_list_after(key: str) -> list:
        pat = re.compile(rf'^\s*{re.escape(key)}:\s*$', re.M)
        mloc = pat.search(text)
        items = []
        if not mloc:
            return items
        start = mloc.end()
        for line in text[mloc.end():].splitlines():
            if re.match(r'^\S', line):  # next top-level key
                break
            mitem = re.match(r'^\s*-\s*(.+?)\s*$', line)
            if mitem:
                items.append(mitem.group(1))
        return items

    cfg["channels"] = parse_list_after("channels")
    cfg["prioritized_themes"] = parse_list_after("prioritized_themes")
    cfg["eco_initiatives"] = parse_list_after("eco_initiatives")
    # newsletter_depends_on_blog
    m = re.search(r'^\s*newsletter_depends_on_blog:\s*(true|false)\s*$', text, re.M | re.I)
    if m:
        cfg["newsletter_depends_on_blog"] = m.group(1).strip().lower() == "true"
    # cadence_per_week block
    c = {}
    pat = re.compile(r'^\s*cadence_per_week:\s*$', re.M)
    m = pat.search(text)
    if m:
        for line in text[m.end():].splitlines():
            if re.match(r'^\S', line):  # next top-level key
                break
            mline = re.match(r'^\s*([a-zA-Z_]+)\s*:\s*(\d+)\s*$', line)
            if mline:
                c[mline.group(1)] = int(mline.group(2))
    cfg["cadence_per_week"] = c
    return cfg


def _load_policy(py_path: Path) -> dict:
    try:
        d = runpy.run_path(str(py_path))
        days_off = d.get("DAYS_OFF", [])
        max_per_day = d.get("MAX_POSTS_PER_DAY", {})
        banned = d.get("BANNED_KEYWORDS", [])
        # Normalize
        if not isinstance(days_off, list):
            days_off = []
        if not isinstance(max_per_day, dict):
            max_per_day = {}
        if not isinstance(banned, list):
            banned = []
        return {
            "DAYS_OFF": [str(x) for x in days_off],
            "MAX_POSTS_PER_DAY": {str(k): int(v) for k, v in max_per_day.items() if isinstance(v, (int, float))},
            "BANNED_KEYWORDS": [str(x) for x in banned],
        }
    except Exception:
        return {}


def _parse_blog_front_matter(md_path: Path) -> dict:
    text = _read_text(md_path)
    if not text:
        return {}
    # Extract YAML front matter between first two --- lines
    m = re.search(r'^---\s*\n(.*?)\n---\s*', text, re.S | re.M)
    fm = m.group(1) if m else ""
    res = {}
    mt = re.search(r'^\s*title:\s*(.+?)\s*$', fm, re.M)
    if mt:
        res["title"] = mt.group(1)
    mt = re.search(r'^\s*theme:\s*(.+?)\s*$', fm, re.M)
    if mt:
        res["theme"] = mt.group(1)
    mt = re.search(r'^\s*status:\s*(.+?)\s*$', fm, re.M)
    if mt:
        res["status"] = mt.group(1).strip()
    return res


def _load_social_snippets(csv_path: Path) -> list:
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for r in reader:
                rows.append({k: (v or "").strip() for k, v in r.items()})
            return rows
    except Exception:
        return []


def _parse_calendar_csv(csv_path: Path) -> tuple:
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return [], []
    if not rows:
        return [], []
    header = rows[0]
    data = []
    for r in rows[1:]:
        if not any(r):
            continue
        # pad to header length
        rr = r + [""] * (len(header) - len(r))
        data.append({header[i]: rr[i].strip() if i < len(rr) else "" for i in range(len(header))})
    return header, data


def _parse_date(s: str):
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _weekday_name(d: date) -> str:
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][d.weekday()]


def _daterange(start: date, days: int):
    for i in range(days):
        yield start + timedelta(days=i)


def _week_index(d: date, start: date) -> int:
    return (d - start).days // 7


def _extract_email_sections(md_text: str) -> dict:
    # Identify Email A and Email B sections by headings containing "Email A" and "Email B"
    sections = {}
    # Normalize line endings
    text = md_text
    # Use regex to capture content following the heading until next heading or end
    a_match = re.search(r'(?is)(^|\n)\s*Email\s*A\s*:?\s*(.*?)(?=(\n\s*Email\s*B\s*:?)|\Z)', text)
    b_match = re.search(r'(?is)(^|\n)\s*Email\s*B\s*:?\s*(.*)\Z', text)
    if a_match:
        sections["email_a"] = a_match.group(2).strip()
    if b_match:
        # If both are found, ensure B content does not include A
        sections["email_b"] = b_match.group(2).strip()
    return sections


def _find_dates_in_text_within(text: str, start: date, end: date) -> set:
    found = set()
    for m in re.finditer(r'\b(20[0-9]{2}-[01][0-9]-[0-3][0-9])\b', text):
        ds = m.group(1)
        try:
            d = date.fromisoformat(ds)
        except Exception:
            continue
        if start <= d <= end:
            found.add(ds)
    return found


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "calendar_file_exists_and_readable": 0.0,
        "calendar_header_structure": 0.0,
        "calendar_date_range_and_days_off": 0.0,
        "calendar_weekday_column_matches_date": 0.0,
        "calendar_weekly_cadence": 0.0,
        "calendar_max_posts_per_day": 0.0,
        "calendar_channels_valid_values": 0.0,
        "calendar_no_duplicate_themes_per_day": 0.0,
        "calendar_source_file_paths_valid": 0.0,
        "calendar_eco_tie_in_uses_initiatives": 0.0,
        "calendar_blog_title_matches_source": 0.0,
        "calendar_no_banned_keywords_in_summaries": 0.0,
        "newsletter_alignment_with_blog": 0.0,
        "emails_file_exists_and_readable": 0.0,
        "email_a_includes_week1_instagram_dates_and_copromotion": 0.0,
        "email_b_mentions_earliest_two_blog_dates_and_themes": 0.0,
        "email_a_no_banned_keywords": 0.0,
        "email_b_no_banned_keywords": 0.0,
    }

    # Load authoritative inputs
    marketing_yaml = workspace / "input" / "config" / "marketing.yaml"
    scheduling_py = workspace / "input" / "config" / "scheduling.py"
    marketing = _parse_marketing_yaml(marketing_yaml) if marketing_yaml.exists() else {}
    policy = _load_policy(scheduling_py) if scheduling_py.exists() else {}

    start_date_str = marketing.get("start_date")
    weeks = marketing.get("weeks")
    cadence = marketing.get("cadence_per_week", {})
    channels_cfg = marketing.get("channels", [])
    eco_initiatives = marketing.get("eco_initiatives", [])
    newsletter_depends = marketing.get("newsletter_depends_on_blog", False)

    days_off = policy.get("DAYS_OFF", [])
    max_per_day = policy.get("MAX_POSTS_PER_DAY", {})
    banned_keywords = [kw.lower() for kw in policy.get("BANNED_KEYWORDS", [])]

    start_date_obj = None
    if start_date_str:
        try:
            start_date_obj = date.fromisoformat(start_date_str)
        except Exception:
            start_date_obj = None

    calendar_csv = workspace / "output" / "content_calendar.csv"
    header, rows = _parse_calendar_csv(calendar_csv) if calendar_csv.exists() else ([], [])
    if calendar_csv.exists() and header:
        scores["calendar_file_exists_and_readable"] = 1.0

    expected_header = [
        "date",
        "weekday",
        "channel",
        "theme",
        "title_or_text_summary",
        "source_file",
        "eco_tie_in",
        "notes",
    ]
    if header == expected_header:
        scores["calendar_header_structure"] = 1.0

    # Calendar validations that require config
    if rows and start_date_obj and isinstance(weeks, int) and weeks > 0 and days_off is not None:
        # date range and days off and weekday matching
        within_range = True
        weekday_ok = True
        days_off_ok = True
        channels_valid = True
        for r in rows:
            ds = r.get("date", "")
            d = _parse_date(ds)
            if d is None:
                within_range = False
                weekday_ok = False
                days_off_ok = False
                continue
            if not (start_date_obj <= d <= start_date_obj + timedelta(days=(7 * weeks - 1))):
                within_range = False
            # weekday
            wname = r.get("weekday", "")
            if _weekday_name(d) != wname:
                weekday_ok = False
            # days off
            if _weekday_name(d) in days_off:
                days_off_ok = False
            # channels valid values
            ch = r.get("channel", "")
            if ch not in ["blog", "instagram", "facebook", "newsletter"]:
                channels_valid = False
        if within_range and days_off_ok:
            scores["calendar_date_range_and_days_off"] = 1.0
        if weekday_ok:
            scores["calendar_weekday_column_matches_date"] = 1.0
        if channels_valid:
            scores["calendar_channels_valid_values"] = 1.0

        # weekly cadence per channel
        cadence_ok = True
        # Build counts week->channel->count
        week_counts = {}
        for r in rows:
            d = _parse_date(r.get("date", ""))
            if d is None:
                cadence_ok = False
                break
            widx = _week_index(d, start_date_obj)
            if widx < 0 or widx >= weeks:
                cadence_ok = False
                break
            ch = r.get("channel", "")
            week_counts.setdefault(widx, {}).setdefault(ch, 0)
            week_counts[widx][ch] += 1
        if cadence_ok:
            for w in range(weeks):
                for ch, needed in cadence.items():
                    actual = week_counts.get(w, {}).get(ch, 0)
                    if actual != needed:
                        cadence_ok = False
                        break
                if not cadence_ok:
                    break
        if cadence_ok:
            scores["calendar_weekly_cadence"] = 1.0

        # MAX_POSTS_PER_DAY per channel
        max_ok = True
        by_date_chan = {}
        for r in rows:
            d = r.get("date", "")
            ch = r.get("channel", "")
            by_date_chan.setdefault(d, {}).setdefault(ch, 0)
            by_date_chan[d][ch] += 1
        for d, ch_counts in by_date_chan.items():
            for ch, cnt in ch_counts.items():
                limit = max_per_day.get(ch, None)
                if limit is None:
                    continue
                if cnt > limit:
                    max_ok = False
                    break
            if not max_ok:
                break
        if max_ok:
            scores["calendar_max_posts_per_day"] = 1.0

        # No duplicate themes on same day (across all channels)
        no_dupes_ok = True
        by_date_themes = {}
        for r in rows:
            d = r.get("date", "")
            theme = r.get("theme", "")
            by_date_themes.setdefault(d, []).append(theme)
        for d, themes in by_date_themes.items():
            tset = set([t for t in themes if t != ""])
            if len(tset) != len(themes):
                no_dupes_ok = False
                break
        if no_dupes_ok:
            scores["calendar_no_duplicate_themes_per_day"] = 1.0

        # Source files valid and blog title matches, eco tie-in, banned keywords in summaries
        paths_ok = True
        blog_titles_ok = True
        ecos_ok = True
        banned_ok = True

        for r in rows:
            src = r.get("source_file", "")
            ch = r.get("channel", "")
            summary = (r.get("title_or_text_summary", "") or "").lower()
            notes = (r.get("notes", "") or "").lower()
            # banned keywords in summaries/notes
            for bad in banned_keywords:
                if bad in summary or bad in notes:
                    banned_ok = False
                    break
            if not banned_ok:
                break
        if banned_ok:
            scores["calendar_no_banned_keywords_in_summaries"] = 1.0

        for r in rows:
            src = r.get("source_file", "")
            eco = r.get("eco_tie_in", "")
            # source file validation
            if src != "new":
                # must exist relative to workspace
                p = workspace / src
                if not p.exists():
                    paths_ok = False
                    break
                # also should be under input/content/
                try:
                    rel = p.relative_to(workspace)
                    if not str(rel).startswith("input/"):
                        paths_ok = False
                        break
                except Exception:
                    paths_ok = False
                    break
            # eco tie-in contains at least one initiative
            if not eco or not any(initiative.lower() in eco.lower() for initiative in eco_initiatives):
                ecos_ok = False
        if paths_ok:
            scores["calendar_source_file_paths_valid"] = 1.0
        if ecos_ok:
            scores["calendar_eco_tie_in_uses_initiatives"] = 1.0

        # Blog title matches source and newsletter alignment
        # Build a cache of blog source -> front matter
        for r in rows:
            if r.get("channel", "") == "blog":
                src = r.get("source_file", "")
                title = r.get("title_or_text_summary", "")
                if src != "new":
                    p = workspace / src
                    if p.suffix.lower() == ".md":
                        fm = _parse_blog_front_matter(p)
                        if not fm or "title" not in fm:
                            blog_titles_ok = False
                            break
                        if fm.get("status", "").lower() == "draft":
                            blog_titles_ok = False
                            break
                        if fm.get("title", "") != title:
                            blog_titles_ok = False
                            break
                else:
                    # new blog title can be any non-empty
                    if not title.strip():
                        blog_titles_ok = False
                        break
        if blog_titles_ok:
            scores["calendar_blog_title_matches_source"] = 1.0

        # Newsletter alignment with blog per week
        align_ok = True
        # Build week->blog_theme (if any, we expect at most one)
        week_blog_theme = {}
        week_has_blog = {}
        for r in rows:
            d = _parse_date(r.get("date", ""))
            if d is None:
                continue
            widx = _week_index(d, start_date_obj)
            if widx < 0 or widx >= weeks:
                continue
            if r.get("channel", "") == "blog":
                week_has_blog[widx] = True
                week_blog_theme[widx] = r.get("theme", "")
        # Validate newsletter
        for r in rows:
            if r.get("channel", "") != "newsletter":
                continue
            d = _parse_date(r.get("date", ""))
            if d is None:
                align_ok = False
                break
            widx = _week_index(d, start_date_obj)
            if widx < 0 or widx >= weeks:
                align_ok = False
                break
            if week_has_blog.get(widx, False):
                expected_theme = week_blog_theme.get(widx, "")
                if r.get("theme", "") != expected_theme:
                    align_ok = False
                    break
            else:
                notes = (r.get("notes", "") or "")
                # require explicit "new content needed" note when no blog
                if "new content needed" not in notes.lower():
                    align_ok = False
                    break
        if align_ok:
            scores["newsletter_alignment_with_blog"] = 1.0

    # Emails validations
    emails_md = workspace / "output" / "outreach_emails.md"
    emails_text = _read_text(emails_md) if emails_md.exists() else ""
    if emails_text:
        scores["emails_file_exists_and_readable"] = 1.0
    sections = _extract_email_sections(emails_text) if emails_text else {}
    email_a = sections.get("email_a", "")
    email_b = sections.get("email_b", "")

    # Gather calendar info for emails
    if rows and start_date_obj and isinstance(weeks, int) and weeks >= 1:
        # Week 1 instagram dates
        w1_start = start_date_obj
        w1_end = start_date_obj + timedelta(days=6)
        insta_dates = sorted(
            {r.get("date", "") for r in rows if r.get("channel", "") == "instagram"
             and _parse_date(r.get("date", "")) is not None
             and w1_start <= _parse_date(r.get("date", "")) <= w1_end}
        )
        if email_a:
            # Check dates presence
            dates_in_email = _find_dates_in_text_within(email_a, w1_start, w1_end)
            dates_ok = all(d in dates_in_email for d in insta_dates) and len(insta_dates) > 0
            # Check co-promotion mention
            copromo_ok = ("co-promotion" in email_a.lower()) or ("co promotion" in email_a.lower()) or ("copromotion" in email_a.lower())
            if dates_ok and copromo_ok:
                scores["email_a_includes_week1_instagram_dates_and_copromotion"] = 1.0
            # Banned keywords not in email
            banned_in_a = any(bad in email_a.lower() for bad in banned_keywords)
            if not banned_in_a:
                scores["email_a_no_banned_keywords"] = 1.0
        # Email B checks
        # Find earliest two blog posts
        blog_rows = []
        for r in rows:
            if r.get("channel", "") == "blog":
                d = _parse_date(r.get("date", ""))
                if d:
                    blog_rows.append((d, r))
        blog_rows.sort(key=lambda x: x[0])
        if len(blog_rows) >= 2 and email_b:
            b1_d, b1_r = blog_rows[0]
            b2_d, b2_r = blog_rows[1]
            # Check both dates are present
            dates_present = (b1_d.isoformat() in email_b) and (b2_d.isoformat() in email_b)
            # Check their themes mentioned
            themes_present = (b1_r.get("theme", "") in email_b) and (b2_r.get("theme", "") in email_b)
            # Check a suggested subject line presence
            subject_present = ("subject:" in email_b.lower()) or ("subject line" in email_b.lower())
            if dates_present and themes_present and subject_present:
                scores["email_b_mentions_earliest_two_blog_dates_and_themes"] = 1.0
            # Banned keywords not in email
            banned_in_b = any(bad in email_b.lower() for bad in banned_keywords)
            if not banned_in_b:
                scores["email_b_no_banned_keywords"] = 1.0
        elif email_b:
            # Even if fewer than two blogs, still enforce banned keyword absence
            banned_in_b = any(bad in email_b.lower() for bad in banned_keywords)
            if not banned_in_b:
                scores["email_b_no_banned_keywords"] = 1.0
    else:
        # Still can check banned keywords absence in emails even without calendar
        if email_a:
            banned_in_a = any(bad in email_a.lower() for bad in banned_keywords)
            if not banned_in_a:
                scores["email_a_no_banned_keywords"] = 1.0
        if email_b:
            banned_in_b = any(bad in email_b.lower() for bad in banned_keywords)
            if not banned_in_b:
                scores["email_b_no_banned_keywords"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()