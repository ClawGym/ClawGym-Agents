import csv
import json
import re
import sys
from statistics import median
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return rows, None
    except Exception as e:
        return None, str(e)


def _to_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        try:
            # try float then int if it's like "10.0"
            f = float(value)
            if f.is_integer():
                return int(f)
            return None
        except Exception:
            return None


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _parse_date_iso(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _round_one_decimal(x: float) -> str:
    return f"{x:.1f}"


def _compute_expected_from_engagement(rows: List[Dict[str, str]]) -> Optional[Dict]:
    # Validate needed columns
    needed = {"date", "platform", "post_id", "topic", "post_title", "likes", "comments", "shares"}
    if not rows:
        return None
    if not set(rows[0].keys()).issuperset(needed):
        return None

    parsed_rows = []
    for i, row in enumerate(rows):
        d = row.get("date", "").strip()
        plat = row.get("platform", "").strip()
        topic = row.get("topic", "").strip()
        likes = _to_int(str(row.get("likes", "")).strip())
        comments = _to_int(str(row.get("comments", "")).strip())
        shares = _to_int(str(row.get("shares", "")).strip())
        # Validate fields
        if not d or _parse_date_iso(d) is None or not plat or not topic or likes is None or comments is None or shares is None:
            return None
        parsed_rows.append({
            "date": d,
            "platform": plat,
            "topic": topic,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "engagement": likes + comments + shares
        })

    dates = [r["date"] for r in parsed_rows]
    date_objs = [_parse_date_iso(d) for d in dates]
    start_date = min(date_objs).strftime("%Y-%m-%d")
    end_date = max(date_objs).strftime("%Y-%m-%d")
    total_posts = len(parsed_rows)
    total_engagement = sum(r["engagement"] for r in parsed_rows)
    avg_engagement_per_post = _round_one_decimal(total_engagement / total_posts) if total_posts > 0 else "0.0"
    comments_list = sorted([r["comments"] for r in parsed_rows])
    med = median(comments_list) if comments_list else 0
    if float(med).is_integer():
        median_comments_str = str(int(med))
    else:
        # ensure .5 preserved
        median_comments_str = f"{med:.1f}".rstrip("0").rstrip(".") if not str(med).endswith(".5") else str(med)

    # Topic aggregation
    topic_totals: Dict[str, Dict[str, float]] = {}
    for r in parsed_rows:
        t = r["topic"]
        topic_totals.setdefault(t, {"total_posts": 0, "total_engagement": 0})
        topic_totals[t]["total_posts"] += 1
        topic_totals[t]["total_engagement"] += r["engagement"]
    topic_sorted = sorted(topic_totals.items(), key=lambda kv: (-kv[1]["total_engagement"], kv[0]))
    top_two = topic_sorted[:2]
    top_two_str_parts = []
    for t, vals in top_two:
        top_two_str_parts.append(f"{t} ({int(vals['total_engagement'])})")
    top_2_topics_str = ", ".join(top_two_str_parts)

    # Platform aggregation
    platform_totals: Dict[str, Dict[str, int]] = {}
    for r in parsed_rows:
        p = r["platform"]
        platform_totals.setdefault(p, {"total_posts": 0, "total_engagement": 0})
        platform_totals[p]["total_posts"] += 1
        platform_totals[p]["total_engagement"] += r["engagement"]
    platform_sorted = sorted(platform_totals.items(), key=lambda kv: (-kv[1]["total_engagement"], kv[0]))
    platform_breakdown_str = ", ".join([f"{p}: {int(vals['total_engagement'])}" for p, vals in platform_sorted])

    # Daily aggregation
    daily_totals: Dict[str, int] = {}
    for r in parsed_rows:
        d = r["date"]
        daily_totals[d] = daily_totals.get(d, 0) + r["engagement"]
    # best day: highest total engagement, tie-breaker earliest date
    best_day_date, best_day_total = None, None
    if daily_totals:
        best_day_date = sorted(daily_totals.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        best_day_total = daily_totals[best_day_date]
    best_day_str = f"{best_day_date} ({int(best_day_total)})" if best_day_date is not None else ""

    # Build aggregates for files
    topic_rows = []
    for t, vals in sorted(topic_totals.items(), key=lambda kv: kv[0]):
        tp = int(vals["total_posts"])
        te = int(vals["total_engagement"])
        avg = te / tp if tp > 0 else 0.0
        topic_rows.append({
            "topic": t,
            "total_posts": tp,
            "total_engagement": te,
            "avg_engagement": avg
        })

    platform_rows = []
    for p, vals in sorted(platform_totals.items(), key=lambda kv: kv[0]):
        platform_rows.append({
            "platform": p,
            "total_posts": int(vals["total_posts"]),
            "total_engagement": int(vals["total_engagement"])
        })

    daily_rows = []
    for d, te in sorted(daily_totals.items(), key=lambda kv: kv[0]):
        daily_rows.append({
            "date": d,
            "total_engagement": int(te)
        })

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_posts": total_posts,
        "total_engagement": total_engagement,
        "avg_engagement_per_post": avg_engagement_per_post,
        "median_comments_str": median_comments_str,
        "top_2_topics_str": top_2_topics_str,
        "best_day_str": best_day_str,
        "platform_breakdown_str": platform_breakdown_str,
        "top_topic": top_two[0][0] if top_two else None,
        "topic_agg_rows": topic_rows,
        "platform_agg_rows": platform_rows,
        "daily_agg_rows": daily_rows,
    }


def _parse_revised_post_at_a_glance(text: str) -> Dict[str, str]:
    # Extract At a glance section heading and bullet values
    result = {
        "date_range": "",
        "Posts analyzed": "",
        "Total engagement (likes + comments + shares)": "",
        "Average engagement per post": "",
        "Top topics by total engagement": "",
        "Median comments per post": "",
        "Busiest day": "",
        "By platform": "",
    }
    lines = text.splitlines()
    # Find heading
    heading_idx = None
    for i, line in enumerate(lines):
        m = re.match(r'^\s*##\s*At a glance\s*\((.*?)\)\s*$', line)
        if m:
            result["date_range"] = m.group(1).strip()
            heading_idx = i
            break
    if heading_idx is None:
        return result

    # Collect bullet lines until next heading or blank line after bullets
    i = heading_idx + 1
    while i < len(lines):
        line = lines[i]
        if re.match(r'^\s*##\s*', line):
            break
        # Parse bullet items
        # Patterns
        bullet_patterns = [
            ("Posts analyzed", r'^\s*-\s*Posts analyzed:\s*(.+)\s*$'),
            ("Total engagement (likes + comments + shares)", r'^\s*-\s*Total engagement \(likes \+ comments \+ shares\):\s*(.+)\s*$'),
            ("Average engagement per post", r'^\s*-\s*Average engagement per post:\s*(.+)\s*$'),
            ("Top topics by total engagement", r'^\s*-\s*Top topics by total engagement:\s*(.+)\s*$'),
            ("Median comments per post", r'^\s*-\s*Median comments per post:\s*(.+)\s*$'),
            ("Busiest day", r'^\s*-\s*Busiest day:\s*(.+)\s*$'),
            ("By platform", r'^\s*-\s*By platform:\s*(.+)\s*$'),
        ]
        for key, pat in bullet_patterns:
            m = re.match(pat, line)
            if m:
                result[key] = m.group(1).strip()
                break
        i += 1
    return result


def _load_aggregate_csv_expected(path: Path, expected_header: List[str]) -> Tuple[Optional[List[Dict[str, str]]], bool]:
    rows, err = _load_csv_dicts(path)
    if rows is None:
        return None, False
    # Validate header exact order
    header_ok = False
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header == expected_header:
                header_ok = True
    except Exception:
        header_ok = False
    if not header_ok:
        return rows, False
    return rows, True


def _build_platform_breakdown_string_from_rows(rows: List[Dict[str, str]]) -> Optional[str]:
    # rows have fields: platform,total_posts,total_engagement
    try:
        accum: Dict[str, Dict[str, int]] = {}
        for r in rows:
            p = r.get("platform", "").strip()
            te = _to_int(str(r.get("total_engagement", "")).strip())
            if not p or te is None:
                return None
            accum[p] = {"total_engagement": te}
        sorted_items = sorted(accum.items(), key=lambda kv: (-kv[1]["total_engagement"], kv[0]))
        return ", ".join([f"{p}: {vals['total_engagement']}" for p, vals in sorted_items])
    except Exception:
        return None


def _build_top2_topics_string_from_rows(rows: List[Dict[str, str]]) -> Optional[str]:
    # rows have fields: topic,total_posts,total_engagement,avg_engagement
    try:
        accum: Dict[str, int] = {}
        for r in rows:
            t = r.get("topic", "").strip()
            te = _to_int(str(r.get("total_engagement", "")).strip())
            if not t or te is None:
                return None
            accum[t] = te
        sorted_items = sorted(accum.items(), key=lambda kv: (-kv[1], kv[0]))
        top = sorted_items[:2]
        parts = [f"{t} ({e})" for t, e in top]
        return ", ".join(parts)
    except Exception:
        return None


def _build_best_day_from_daily_rows(rows: List[Dict[str, str]]) -> Optional[str]:
    try:
        accum: Dict[str, int] = {}
        for r in rows:
            d = r.get("date", "").strip()
            te = _to_int(str(r.get("total_engagement", "")).strip())
            if not d or _parse_date_iso(d) is None or te is None:
                return None
            accum[d] = te
        if not accum:
            return None
        best = sorted(accum.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        return f"{best[0]} ({best[1]})"
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "aggregates_topic_file_valid": 0.0,
        "aggregates_platform_file_valid": 0.0,
        "aggregates_daily_file_valid": 0.0,
        "aggregates_topic_values_correct": 0.0,
        "aggregates_platform_values_correct": 0.0,
        "aggregates_daily_values_correct": 0.0,
        "revised_post_exists": 0.0,
        "revised_post_placeholders_replaced": 0.0,
        "revised_post_date_range_correct": 0.0,
        "revised_post_total_posts_correct": 0.0,
        "revised_post_total_engagement_correct": 0.0,
        "revised_post_avg_engagement_correct": 0.0,
        "revised_post_top_2_topics_correct": 0.0,
        "revised_post_median_comments_correct": 0.0,
        "revised_post_best_day_correct": 0.0,
        "revised_post_platform_breakdown_correct": 0.0,
        "internal_consistency_post_vs_aggregates": 0.0,
        "social_update_exists": 0.0,
        "social_update_within_length": 0.0,
        "social_update_includes_date_range": 0.0,
        "social_update_includes_top_topic": 0.0,
        "social_update_includes_numeric_metric": 0.0,
        "social_update_includes_phrase": 0.0,
    }

    # Load input engagement log to compute expected values
    input_csv = workspace / "input" / "engagement_log.csv"
    input_rows, input_err = _load_csv_dicts(input_csv)
    expected = None
    if input_rows is not None:
        expected = _compute_expected_from_engagement(input_rows)

    # Validate aggregate files existence, headers, and values vs expected
    aggr_dir = workspace / "output" / "aggregates"
    topic_csv = aggr_dir / "topic_engagement.csv"
    platform_csv = aggr_dir / "platform_engagement.csv"
    daily_csv = aggr_dir / "daily_engagement.csv"

    topic_rows, topic_header_ok = _load_aggregate_csv_expected(
        topic_csv, ["topic", "total_posts", "total_engagement", "avg_engagement"]
    )
    platform_rows, platform_header_ok = _load_aggregate_csv_expected(
        platform_csv, ["platform", "total_posts", "total_engagement"]
    )
    daily_rows, daily_header_ok = _load_aggregate_csv_expected(
        daily_csv, ["date", "total_engagement"]
    )

    if topic_rows is not None and topic_header_ok:
        scores["aggregates_topic_file_valid"] = 1.0
    if platform_rows is not None and platform_header_ok:
        scores["aggregates_platform_file_valid"] = 1.0
    if daily_rows is not None and daily_header_ok:
        scores["aggregates_daily_file_valid"] = 1.0

    # Aggregates content correctness vs expected
    if expected is not None and topic_rows is not None and topic_header_ok:
        # Compare sets and values
        ok = True
        expected_map = {r["topic"]: r for r in expected["topic_agg_rows"]}
        seen_topics = set()
        for r in topic_rows:
            t = r.get("topic", "").strip()
            tp = _to_int(str(r.get("total_posts", "")).strip())
            te = _to_int(str(r.get("total_engagement", "")).strip())
            avg = _to_float(str(r.get("avg_engagement", "")).strip())
            if not t or tp is None or te is None or avg is None:
                ok = False
                break
            if t not in expected_map:
                ok = False
                break
            exp = expected_map[t]
            if tp != int(exp["total_posts"]) or te != int(exp["total_engagement"]):
                ok = False
                break
            exp_avg = exp["avg_engagement"]
            # strict equality within small tolerance
            if abs(avg - float(exp_avg)) > 1e-6:
                ok = False
                break
            seen_topics.add(t)
        # Ensure no missing or extra topics
        if ok and seen_topics != set(expected_map.keys()):
            ok = False
        scores["aggregates_topic_values_correct"] = 1.0 if ok else 0.0

    if expected is not None and platform_rows is not None and platform_header_ok:
        ok = True
        expected_map = {r["platform"]: r for r in expected["platform_agg_rows"]}
        seen_platforms = set()
        for r in platform_rows:
            p = r.get("platform", "").strip()
            tp = _to_int(str(r.get("total_posts", "")).strip())
            te = _to_int(str(r.get("total_engagement", "")).strip())
            if not p or tp is None or te is None:
                ok = False
                break
            if p not in expected_map:
                ok = False
                break
            exp = expected_map[p]
            if tp != int(exp["total_posts"]) or te != int(exp["total_engagement"]):
                ok = False
                break
            seen_platforms.add(p)
        if ok and seen_platforms != set(expected_map.keys()):
            ok = False
        scores["aggregates_platform_values_correct"] = 1.0 if ok else 0.0

    if expected is not None and daily_rows is not None and daily_header_ok:
        ok = True
        expected_map = {r["date"]: r for r in expected["daily_agg_rows"]}
        seen_dates = set()
        for r in daily_rows:
            d = r.get("date", "").strip()
            te = _to_int(str(r.get("total_engagement", "")).strip())
            if not d or _parse_date_iso(d) is None or te is None:
                ok = False
                break
            if d not in expected_map:
                ok = False
                break
            exp = expected_map[d]
            if te != int(exp["total_engagement"]):
                ok = False
                break
            seen_dates.add(d)
        if ok and seen_dates != set(expected_map.keys()):
            ok = False
        scores["aggregates_daily_values_correct"] = 1.0 if ok else 0.0

    # Validate revised_post.md
    revised_path = workspace / "output" / "revised_post.md"
    revised_text = _read_text(revised_path)
    if revised_text is not None:
        scores["revised_post_exists"] = 1.0
        # placeholders replaced
        scores["revised_post_placeholders_replaced"] = 1.0 if ("{{" not in revised_text and "}}" not in revised_text) else 0.0
        glance = _parse_revised_post_at_a_glance(revised_text)
        # Check date range in heading
        if expected is not None:
            expected_range = f"{expected['start_date']} to {expected['end_date']}"
            if glance.get("date_range", "") == expected_range:
                scores["revised_post_date_range_correct"] = 1.0
        # Check Posts analyzed
        if expected is not None:
            if glance.get("Posts analyzed", "") == str(expected["total_posts"]):
                scores["revised_post_total_posts_correct"] = 1.0
        # Total engagement
        if expected is not None:
            if glance.get("Total engagement (likes + comments + shares)", "") == str(expected["total_engagement"]):
                scores["revised_post_total_engagement_correct"] = 1.0
        # Average per post
        if expected is not None:
            if glance.get("Average engagement per post", "") == str(expected["avg_engagement_per_post"]):
                scores["revised_post_avg_engagement_correct"] = 1.0
        # Top 2 topics
        if expected is not None:
            if glance.get("Top topics by total engagement", "") == expected["top_2_topics_str"]:
                scores["revised_post_top_2_topics_correct"] = 1.0
        # Median comments
        if expected is not None:
            if glance.get("Median comments per post", "") == expected["median_comments_str"]:
                scores["revised_post_median_comments_correct"] = 1.0
        # Best day
        if expected is not None:
            if glance.get("Busiest day", "") == expected["best_day_str"]:
                scores["revised_post_best_day_correct"] = 1.0
        # Platform breakdown
        if expected is not None:
            if glance.get("By platform", "") == expected["platform_breakdown_str"]:
                scores["revised_post_platform_breakdown_correct"] = 1.0

        # Internal consistency between post and aggregates
        consistent = True
        if topic_rows is None or not topic_header_ok or platform_rows is None or not platform_header_ok or daily_rows is None or not daily_header_ok:
            consistent = False
        else:
            # Build strings from aggregates and compare to post values
            top2_from_agg = _build_top2_topics_string_from_rows(topic_rows)
            plat_from_agg = _build_platform_breakdown_string_from_rows(platform_rows)
            best_from_agg = _build_best_day_from_daily_rows(daily_rows)
            if top2_from_agg is None or plat_from_agg is None or best_from_agg is None:
                consistent = False
            else:
                if glance.get("Top topics by total engagement", "") != top2_from_agg:
                    consistent = False
                if glance.get("By platform", "") != plat_from_agg:
                    consistent = False
                if glance.get("Busiest day", "") != best_from_agg:
                    consistent = False
                # Sum totals across aggregates to match post totals
                try:
                    # platform totals sum
                    plat_total = sum(_to_int(r["total_engagement"]) or 0 for r in platform_rows)
                    # daily totals sum
                    daily_total = sum(_to_int(r["total_engagement"]) or 0 for r in daily_rows)
                    # topic totals sum
                    topic_total = sum(_to_int(r["total_engagement"]) or 0 for r in topic_rows)
                    # posts totals
                    plat_posts = sum(_to_int(r["total_posts"]) or 0 for r in platform_rows)
                    topic_posts = sum(_to_int(r["total_posts"]) or 0 for r in topic_rows)
                    total_posts_post = _to_int(glance.get("Posts analyzed", ""))
                    total_engagement_post = _to_int(glance.get("Total engagement (likes + comments + shares)", ""))

                    if None in (total_posts_post, total_engagement_post):
                        consistent = False
                    else:
                        if not (plat_total == daily_total == topic_total == total_engagement_post):
                            consistent = False
                        if not (plat_posts == topic_posts == total_posts_post):
                            consistent = False
                except Exception:
                    consistent = False

        scores["internal_consistency_post_vs_aggregates"] = 1.0 if consistent else 0.0

    # Validate social update
    social_path = workspace / "output" / "social_update.txt"
    social_text = _read_text(social_path)
    if social_text is not None:
        scores["social_update_exists"] = 1.0
        text = social_text.strip()
        if len(text) <= 280:
            scores["social_update_within_length"] = 1.0
        if expected is not None:
            start = expected["start_date"]
            end = expected["end_date"]
            if start in text and end in text:
                scores["social_update_includes_date_range"] = 1.0
            # Include top topic
            top_topic = expected.get("top_topic")
            if top_topic and top_topic in text:
                scores["social_update_includes_top_topic"] = 1.0
        # Include numeric metric
        if re.search(r"\d", text):
            scores["social_update_includes_numeric_metric"] = 1.0
        # Includes phrase "Subjective Sunday"
        if "Subjective Sunday" in text:
            scores["social_update_includes_phrase"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()