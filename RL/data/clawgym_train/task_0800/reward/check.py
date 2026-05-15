import json
import sys
import math
import csv
import re
from pathlib import Path
from datetime import date, timedelta


def _read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        try:
            return p.read_text(encoding="utf-8-sig")
        except Exception:
            return ""


def _load_csv_dicts(p: Path):
    try:
        text = _read_text_safe(p)
        if not text.strip():
            return None
        lines = text.splitlines()
        reader = csv.DictReader(lines)
        rows = [dict(r) for r in reader]
        # Normalize keys by stripping whitespace
        normalized_rows = []
        for r in rows:
            normalized_rows.append({(k.strip() if isinstance(k, str) else k): v for k, v in r.items()})
        return normalized_rows
    except Exception:
        return None


def _parse_float(s):
    try:
        return float(s)
    except Exception:
        return None


def _get_csv_header(p: Path):
    try:
        text = _read_text_safe(p)
        if not text:
            return None
        first_line = text.splitlines()[0]
        reader = csv.reader([first_line])
        hdr = next(reader)
        return [h.strip() for h in hdr]
    except Exception:
        return None


def _compute_priority_scores(eng_rows):
    results = []
    for r in eng_rows:
        theme = r.get("theme", "")
        ac = _parse_float(r.get("avg_clicks", ""))
        am = _parse_float(r.get("avg_comments", ""))
        ss = _parse_float(r.get("sample_size", ""))
        if theme == "" or ac is None or am is None or ss is None:
            return None
        score = (0.6 * ac + 0.4 * am) * math.log(ss + 1)
        results.append({
            "theme": theme,
            "avg_clicks": ac,
            "avg_comments": am,
            "sample_size": int(ss),
            "priority_score": score
        })
    results_sorted = sorted(results, key=lambda x: (-x["priority_score"], x["theme"]))
    for idx, item in enumerate(results_sorted, start=1):
        item["rank"] = idx
        item["priority_score_rounded"] = round(item["priority_score"] + 1e-12, 2)
    return results_sorted


def _format_two_decimals(val: float) -> str:
    return f"{val:.2f}"


def _may_2026_week_dates():
    first_day = date(2026, 5, 1)
    d = first_day
    while d.weekday() != 0:  # Monday=0
        d += timedelta(days=1)
    weeks = []
    for w in range(4):
        week_start = d + timedelta(days=7 * w)
        week_dates = [week_start, week_start + timedelta(days=2), week_start + timedelta(days=5)]  # Mon, Wed, Sat
        weeks.append(week_dates)
    return weeks


def _expected_mws_dates_may_2026():
    weeks = _may_2026_week_dates()
    all_dates = [dt.isoformat() for week in weeks for dt in week]
    return all_dates


def _date_to_week_index():
    mapping = {}
    weeks = _may_2026_week_dates()
    for i, week in enumerate(weeks, start=1):
        for dt in week:
            mapping[dt.isoformat()] = i
    return mapping


def _dow_name(dt: date) -> str:
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][dt.weekday()]


def _split_sentences(text: str):
    parts = re.split(r'[.!?]+', text)
    cleaned = [p.strip() for p in parts if p.strip()]
    return cleaned


def _load_post_ideas(workspace: Path):
    ideas_path = workspace / "input" / "post_ideas.csv"
    rows = _load_csv_dicts(ideas_path)
    if rows is None:
        return None
    ideas = {}
    for r in rows:
        idea_id = r.get("idea_id", "").strip()
        if not idea_id:
            continue
        ideas[idea_id] = r
    return ideas


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ideas_ranked_columns": 0.0,
        "ideas_ranked_values": 0.0,
        "ideas_ranked_order_and_rank": 0.0,
        "calendar_columns": 0.0,
        "calendar_dates_and_count": 0.0,
        "calendar_day_of_week_and_platform": 0.0,
        "calendar_unique_ideas_and_seasonality": 0.0,
        "calendar_event_posts": 0.0,
        "calendar_theme_minimums": 0.0,
        "calendar_weekly_nostalgia": 0.0,
        "calendar_post_copy_sentence_count": 0.0,
        "calendar_nostalgia_tie_to_gardening": 0.0,
        "brief_sections_present": 0.0,
        "brief_exec_summary_length": 0.0,
        "brief_theme_ranking_summary": 0.0,
        "brief_weekly_plan_overview": 0.0,
        "brief_constraint_check": 0.0,
    }

    # Load inputs
    eng_path = workspace / "input" / "engagement_history.csv"
    eng_rows = _load_csv_dicts(eng_path)
    ideas_rank_expected = None
    if eng_rows is not None:
        ideas_rank_expected = _compute_priority_scores(eng_rows)

    post_ideas = _load_post_ideas(workspace)

    # Check outputs/ideas_ranked.csv
    ideas_ranked_path = workspace / "outputs" / "ideas_ranked.csv"
    ideas_ranked_rows = _load_csv_dicts(ideas_ranked_path)
    header = _get_csv_header(ideas_ranked_path)
    expected_header = ["theme", "avg_clicks", "avg_comments", "sample_size", "priority_score", "rank"]
    if header == expected_header and ideas_ranked_rows is not None and len(ideas_ranked_rows) > 0:
        scores["ideas_ranked_columns"] = 1.0

    # Check values and order if we have both inputs and outputs
    if ideas_rank_expected is not None and ideas_ranked_rows is not None and header == expected_header:
        if len(ideas_ranked_rows) == len(ideas_rank_expected):
            exp_by_theme = {x["theme"]: x for x in ideas_rank_expected}
            values_ok = True
            order_ok = True

            for i, r in enumerate(ideas_ranked_rows):
                theme = r.get("theme", "")
                if theme not in exp_by_theme:
                    values_ok = False
                    break
                exp = exp_by_theme[theme]
                ac = _parse_float(r.get("avg_clicks", ""))
                am = _parse_float(r.get("avg_comments", ""))
                ss = _parse_float(r.get("sample_size", ""))
                if ac is None or am is None or ss is None:
                    values_ok = False
                    break
                if abs(ac - exp["avg_clicks"]) > 1e-9 or abs(am - exp["avg_comments"]) > 1e-9 or int(ss) != int(exp["sample_size"]):
                    values_ok = False
                    break
                ps = _parse_float(r.get("priority_score", ""))
                if ps is None:
                    values_ok = False
                    break
                if round(ps + 1e-12, 2) != exp["priority_score_rounded"]:
                    values_ok = False
                    break
            try:
                provided_scores = [float(r["priority_score"]) for r in ideas_ranked_rows]
            except Exception:
                provided_scores = None
            provided_themes = [r.get("theme", "") for r in ideas_ranked_rows]
            provided_ranks = []
            ranks_parsable = True
            for r in ideas_ranked_rows:
                try:
                    provided_ranks.append(int(r.get("rank", "")))
                except Exception:
                    ranks_parsable = False
                    break
            if provided_scores is not None and ranks_parsable:
                seq_ok = provided_ranks == list(range(1, len(provided_ranks) + 1))
                expected_order = [x["theme"] for x in ideas_rank_expected]
                order_ok = seq_ok and (provided_themes == expected_order)
            else:
                order_ok = False

            if values_ok:
                scores["ideas_ranked_values"] = 1.0
            if order_ok:
                scores["ideas_ranked_order_and_rank"] = 1.0

    # Calendar checks
    calendar_path = workspace / "outputs" / "calendar.csv"
    calendar_rows = _load_csv_dicts(calendar_path)
    cal_header = _get_csv_header(calendar_path)
    expected_calendar_header = ["date", "day_of_week", "platform", "idea_id", "theme", "post_copy", "image_hint"]
    if cal_header == expected_calendar_header and calendar_rows is not None and len(calendar_rows) > 0:
        scores["calendar_columns"] = 1.0

    expected_dates = set(_expected_mws_dates_may_2026())
    if calendar_rows is not None and cal_header == expected_calendar_header:
        date_values = [r.get("date", "") for r in calendar_rows]
        if len(calendar_rows) == 12 and set(date_values) == expected_dates and len(set(date_values)) == 12:
            scores["calendar_dates_and_count"] = 1.0

        dow_platform_ok = True
        for r in calendar_rows:
            dstr = r.get("date", "")
            dow = r.get("day_of_week", "")
            plat = r.get("platform", "")
            try:
                y, m, d = [int(x) for x in dstr.split("-")]
                dt = date(y, m, d)
            except Exception:
                dow_platform_ok = False
                break
            if _dow_name(dt) != dow:
                dow_platform_ok = False
                break
            if plat != "Facebook":
                dow_platform_ok = False
                break
        if dow_platform_ok:
            scores["calendar_day_of_week_and_platform"] = 1.0

        unique_ok = True
        seen_ids = set()
        season_ok = True
        theme_match_ok = True
        image_hint_ok = True
        if post_ideas is None:
            unique_ok = False
            season_ok = False
            theme_match_ok = False
        else:
            for r in calendar_rows:
                idea_id = (r.get("idea_id", "") or "").strip()
                theme = (r.get("theme", "") or "").strip()
                if not idea_id:
                    unique_ok = False
                if idea_id in seen_ids:
                    unique_ok = False
                seen_ids.add(idea_id)
                idea_info = post_ideas.get(idea_id)
                if idea_info is None:
                    season_ok = False
                    theme_match_ok = False
                else:
                    if (idea_info.get("theme", "") or "").strip() != theme:
                        theme_match_ok = False
                    months = (idea_info.get("seasonality_months", "") or "").split("|")
                    months = [m.strip() for m in months if m.strip()]
                    if "5" not in months:
                        season_ok = False
                ih = (r.get("image_hint", "") or "").strip()
                if ih == "":
                    image_hint_ok = False
        if unique_ok and season_ok and theme_match_ok and image_hint_ok:
            scores["calendar_unique_ideas_and_seasonality"] = 1.0

        event_ok = True
        events_path = workspace / "input" / "events.csv"
        events_rows = _load_csv_dicts(events_path)
        expected_event_map = {
            "2026-05-09": ("EP01", "event_promo"),
            "2026-05-20": ("EP02", "event_promo"),
        }
        if events_rows is None:
            event_ok = False
        else:
            cal_by_date = {r.get("date", ""): r for r in calendar_rows}
            for ev_date, (exp_id, exp_theme) in expected_event_map.items():
                r = cal_by_date.get(ev_date)
                if r is None:
                    event_ok = False
                    break
                if (r.get("idea_id", "") or "").strip() != exp_id:
                    event_ok = False
                    break
                if (r.get("theme", "") or "").strip() != exp_theme:
                    event_ok = False
                    break
        if event_ok:
            scores["calendar_event_posts"] = 1.0

        theme_counts = {}
        for r in calendar_rows:
            t = (r.get("theme", "") or "").strip()
            theme_counts[t] = theme_counts.get(t, 0) + 1
        if theme_counts.get("gardening_tip", 0) >= 6 and theme_counts.get("product_promo", 0) >= 2:
            scores["calendar_theme_minimums"] = 1.0

        date_week = _date_to_week_index()
        weekly_ok = True
        week_has_nf = {1: False, 2: False, 3: False, 4: False}
        for r in calendar_rows:
            d = r.get("date", "")
            t = (r.get("theme", "") or "").strip()
            w = date_week.get(d)
            if w in week_has_nf:
                if t == "nostalgia_football":
                    week_has_nf[w] = True
        for w in range(1, 5):
            if not week_has_nf.get(w, False):
                weekly_ok = False
                break
        if weekly_ok:
            scores["calendar_weekly_nostalgia"] = 1.0

        sentence_ok = True
        nostalgia_tie_ok = True
        sports_terms = {"match", "football", "stadium", "terrace", "scarf", "goal", "kick-off", "kickoff", "matchday", "match-day", "half-time", "halftime"}
        garden_terms = {"garden", "gardening", "plants", "plant", "seedling", "seedlings", "soil", "watering", "pruning", "mulch", "compost", "beds", "trowel", "seeds", "weeds", "roots", "tomato", "lettuce", "carrot", "bloom", "flowers"}
        for r in calendar_rows:
            pc = (r.get("post_copy", "") or "").strip()
            if not pc:
                sentence_ok = False
                nostalgia_tie_ok = False
                break
            sents = _split_sentences(pc)
            if len(sents) < 1 or len(sents) > 2:
                sentence_ok = False
            if (r.get("theme", "") or "").strip() == "nostalgia_football":
                txt = pc.lower()
                has_sport = any(term in txt for term in sports_terms)
                has_garden = any(term in txt for term in garden_terms)
                if not (has_sport and has_garden):
                    nostalgia_tie_ok = False
        if sentence_ok:
            scores["calendar_post_copy_sentence_count"] = 1.0
        if nostalgia_tie_ok:
            scores["calendar_nostalgia_tie_to_gardening"] = 1.0

    # Brief checks
    brief_path = workspace / "outputs" / "brief.md"
    brief_text = _read_text_safe(brief_path)
    if brief_text:
        def has_heading(t, h):
            return re.search(rf'^\s*#*\s*{re.escape(h)}\s*$', t, flags=re.IGNORECASE | re.MULTILINE) is not None

        sections_present = all([
            has_heading(brief_text, "Executive Summary"),
            has_heading(brief_text, "Theme Ranking Summary"),
            has_heading(brief_text, "Weekly Plan Overview"),
            has_heading(brief_text, "Constraint Check")
        ])
        if sections_present:
            scores["brief_sections_present"] = 1.0

        def extract_section(t, heading):
            headings = ["Executive Summary", "Theme Ranking Summary", "Weekly Plan Overview", "Constraint Check"]
            pattern = re.compile(rf'^\s*#*\s*{re.escape(heading)}\s*$', flags=re.IGNORECASE | re.MULTILINE)
            m = pattern.search(t)
            if not m:
                return ""
            start = m.end()
            next_pos = len(t)
            for h in headings:
                if h.lower() == heading.lower():
                    continue
                m2 = re.compile(rf'^\s*#*\s*{re.escape(h)}\s*$', flags=re.IGNORECASE | re.MULTILINE).search(t, pos=start)
                if m2:
                    next_pos = min(next_pos, m2.start())
            return t[start:next_pos].strip()

        exec_sec = extract_section(brief_text, "Executive Summary")
        if exec_sec:
            words = re.findall(r'\b\w+\b', exec_sec)
            if 150 <= len(words) <= 250:
                scores["brief_exec_summary_length"] = 1.0

        trs_sec = extract_section(brief_text, "Theme Ranking Summary")
        ranking_ok = False
        if trs_sec and ideas_rank_expected is not None:
            ranking_ok = True
            for item in ideas_rank_expected:
                theme = item["theme"]
                score_str = _format_two_decimals(item["priority_score_rounded"])
                rank_num = item["rank"]
                found_for_theme = False
                for m in re.finditer(re.escape(theme), trs_sec, flags=re.IGNORECASE):
                    start = max(0, m.start() - 100)
                    end = min(len(trs_sec), m.end() + 100)
                    window = trs_sec[start:end]
                    if (score_str in window) and (re.search(rf'\brank\b[^0-9]*{rank_num}\b', window, flags=re.IGNORECASE) or re.search(rf'\b{rank_num}\b[^a-zA-Z]*\brank\b', window, flags=re.IGNORECASE)):
                        found_for_theme = True
                        break
                if not found_for_theme:
                    ranking_ok = False
                    break
        if ranking_ok:
            scores["brief_theme_ranking_summary"] = 1.0

        wpo_sec = extract_section(brief_text, "Weekly Plan Overview")
        wpo_ok = False
        if wpo_sec and calendar_rows is not None:
            weeks_labels_ok = all(re.search(rf'\bWeek\s+{i}\b', wpo_sec, flags=re.IGNORECASE) for i in range(1, 5))
            lines = [ln.strip() for ln in wpo_sec.splitlines() if ln.strip()]
            date_theme_ok = True
            for r in calendar_rows:
                d = r.get("date", "")
                t = (r.get("theme", "") or "").strip()
                line_has = any((d in ln) and (t in ln) for ln in lines)
                if not line_has:
                    date_theme_ok = False
                    break
            wpo_ok = weeks_labels_ok and date_theme_ok
        if wpo_ok:
            scores["brief_weekly_plan_overview"] = 1.0

        cc_sec = extract_section(brief_text, "Constraint Check")
        cc_ok = False
        if cc_sec and calendar_rows is not None:
            actual_counts = {}
            for r in calendar_rows:
                t = (r.get("theme", "") or "").strip()
                actual_counts[t] = actual_counts.get(t, 0) + 1
            reported = {}
            for ln in cc_sec.splitlines():
                for theme in ["gardening_tip", "product_promo", "nostalgia_football", "event_promo"]:
                    if re.search(rf'\b{re.escape(theme)}\b', ln, flags=re.IGNORECASE):
                        m = re.search(r'(\d+)', ln)
                        if m:
                            reported[theme] = int(m.group(1))
            counts_match = True
            for theme, cnt in actual_counts.items():
                if theme in ["gardening_tip", "product_promo", "nostalgia_football", "event_promo"]:
                    if reported.get(theme) != cnt:
                        counts_match = False
                        break
            nf_phrase = re.search(r'at\s+least\s+1\s+nostalgia_football\s+per\s+week', cc_sec, flags=re.IGNORECASE) is not None
            promo_phrase = re.search(r'at\s+least\s+2\s+product_promo', cc_sec, flags=re.IGNORECASE) is not None
            events_present = ("2026-05-09" in cc_sec) and ("2026-05-20" in cc_sec)
            cc_ok = counts_match and nf_phrase and promo_phrase and events_present
        if cc_ok:
            scores["brief_constraint_check"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()