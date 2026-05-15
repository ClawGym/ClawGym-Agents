import sys
import json
import csv
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from statistics import median as _median


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _parse_int(x: Any) -> Optional[int]:
    try:
        if isinstance(x, int):
            return x
        if isinstance(x, float) and x.is_integer():
            return int(x)
        s = str(x).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None


def _safe_median(vals: List[float]) -> float:
    return float(_median(vals)) if vals else 0.0


def _compute_per_post_metrics(past_posts: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    processed = []
    for row in past_posts:
        try:
            impressions = _parse_float(row.get("impressions"))
            clicks = _parse_float(row.get("clicks"))
            saves = _parse_float(row.get("saves"))
            comments = _parse_float(row.get("comments"))
            if None in (impressions, clicks, saves, comments):
                return None
            if impressions == 0:
                return None
            er = (clicks + saves + comments) / impressions
            ctr = clicks / impressions
            new_row = dict(row)
            new_row["_impressions"] = float(impressions)
            new_row["_engagement_rate"] = float(er)
            new_row["_ctr"] = float(ctr)
            processed.append(new_row)
        except Exception:
            return None
    return processed


def _group_aggregates(rows: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        k = r.get(key)
        if k is None:
            return None
        groups.setdefault(k, []).append(r)
    agg: Dict[str, Dict[str, Any]] = {}
    for k, items in groups.items():
        impressions_list = [float(item["_impressions"]) for item in items]
        ers = [float(item["_engagement_rate"]) for item in items]
        ctrs = [float(item["_ctr"]) for item in items]
        posts_count = len(items)
        mean_er = sum(ers) / posts_count if posts_count else 0.0
        med_impr = _safe_median(impressions_list)
        mean_ctr = sum(ctrs) / posts_count if posts_count else 0.0
        agg[k] = {
            "posts_count": posts_count,
            "mean_engagement_rate": mean_er,
            "median_impressions": med_impr,
            "mean_ctr": mean_ctr,
        }
    return agg


def _load_aggregates_csv(path: Path, key_field: str) -> Optional[Dict[str, Dict[str, Any]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    result: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        k = r.get(key_field)
        if k is None:
            return None
        posts_count = _parse_int(r.get("posts_count"))
        mean_er = _parse_float(r.get("mean_engagement_rate"))
        med_impr = _parse_float(r.get("median_impressions"))
        mean_ctr = _parse_float(r.get("mean_ctr"))
        if None in (posts_count, mean_er, med_impr, mean_ctr):
            return None
        result[k] = {
            "posts_count": posts_count,
            "mean_engagement_rate": mean_er,
            "median_impressions": med_impr,
            "mean_ctr": mean_ctr,
        }
    return result


def _headers_match_exact(path: Path, expected_headers: List[str]) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            return header == expected_headers
    except Exception:
        return False


def _compare_float(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _compare_median(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= 0.5


def _recompute_expected_aggregates(past_posts_path: Path) -> Tuple[Optional[Dict[str, Dict[str, Any]]], Optional[Dict[str, Dict[str, Any]]]]:
    past_posts = _read_csv_dicts(past_posts_path)
    if past_posts is None:
        return None, None
    per_post = _compute_per_post_metrics(past_posts)
    if per_post is None:
        return None, None
    by_topic = _group_aggregates(per_post, "topic_tag")
    by_channel = _group_aggregates(per_post, "channel")
    return by_topic, by_channel


def _load_rankings_csv(path: Path, key_field: str) -> Optional[List[Dict[str, Any]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    parsed_rows = []
    for r in rows:
        k = r.get(key_field)
        rank = _parse_int(r.get("rank"))
        mean_er = _parse_float(r.get("mean_engagement_rate"))
        med_impr = _parse_float(r.get("median_impressions"))
        posts_count = _parse_int(r.get("posts_count"))
        if None in (k, rank, mean_er, med_impr, posts_count):
            return None
        parsed_rows.append({
            key_field: k,
            "rank": rank,
            "mean_engagement_rate": mean_er,
            "median_impressions": med_impr,
            "posts_count": posts_count
        })
    return parsed_rows


def _sort_ranking_from_aggs(aggs: Dict[str, Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    items = list(aggs.items())
    items.sort(key=lambda kv: (-kv[1]["mean_engagement_rate"], -kv[1]["median_impressions"], kv[0]))
    return items


def _read_content_plan(path: Path) -> Optional[List[Dict[str, Any]]]:
    return _read_csv_dicts(path)


def _read_calendar_skeleton(path: Path) -> Optional[List[Dict[str, Any]]]:
    return _read_csv_dicts(path)


def _iso_week(date_str: str) -> Optional[int]:
    from datetime import date
    try:
        parts = [int(p) for p in date_str.split("-")]
        if len(parts) != 3:
            return None
        y, m, d = parts
        return date(y, m, d).isocalendar()[1]
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "aggregates_by_topic_header_and_values": 0.0,
        "aggregates_by_channel_header_and_values": 0.0,
        "rankings_topics_header_and_order": 0.0,
        "rankings_channels_header_and_order": 0.0,
        "content_plan_header_and_slots_match_skeleton": 0.0,
        "content_plan_no_duplicate_date_channel": 0.0,
        "content_plan_topics_allowed": 0.0,
        "content_plan_focus_topics_fraction": 0.0,
        "content_plan_goals_and_ctas_valid": 0.0,
        "content_plan_top_topic_weekly": 0.0,
        "validation_report_present": 0.0,
        "validation_summary_passed": 0.0,
        "sample_topic_metric_consistency": 0.0,
    }

    past_posts_path = workspace / "input" / "past_posts.csv"
    calendar_skeleton_path = workspace / "input" / "calendar_skeleton.csv"
    research_notes_path = workspace / "input" / "research_notes.json"

    agg_topic_path = workspace / "outputs" / "aggregates" / "by_topic.csv"
    agg_channel_path = workspace / "outputs" / "aggregates" / "by_channel.csv"
    rank_topics_path = workspace / "outputs" / "rankings" / "topics.csv"
    rank_channels_path = workspace / "outputs" / "rankings" / "channels.csv"
    plan_path = workspace / "outputs" / "plan" / "content_plan.csv"
    val_report_path = workspace / "outputs" / "validation" / "test_report.txt"
    val_summary_path = workspace / "outputs" / "validation" / "summary.json"

    expected_agg_topic_headers = ["topic_tag", "posts_count", "mean_engagement_rate", "median_impressions", "mean_ctr"]
    expected_agg_channel_headers = ["channel", "posts_count", "mean_engagement_rate", "median_impressions", "mean_ctr"]
    expected_rank_topics_headers = ["topic_tag", "rank", "mean_engagement_rate", "median_impressions", "posts_count"]
    expected_rank_channels_headers = ["channel", "rank", "mean_engagement_rate", "median_impressions", "posts_count"]
    expected_plan_headers = ["date", "channel", "slot_time", "preferred_format", "topic_tag", "post_title", "goal", "cta"]

    expected_by_topic, expected_by_channel = _recompute_expected_aggregates(past_posts_path)

    if agg_topic_path.exists() and expected_by_topic is not None:
        if _headers_match_exact(agg_topic_path, expected_agg_topic_headers):
            loaded_topic_aggs = _load_aggregates_csv(agg_topic_path, "topic_tag")
            if loaded_topic_aggs is not None:
                if set(loaded_topic_aggs.keys()) == set(expected_by_topic.keys()):
                    all_ok = True
                    for topic, exp in expected_by_topic.items():
                        got = loaded_topic_aggs.get(topic)
                        if got is None:
                            all_ok = False
                            break
                        if got["posts_count"] != exp["posts_count"]:
                            all_ok = False
                            break
                        if not _compare_float(got["mean_engagement_rate"], exp["mean_engagement_rate"], tol=1e-4):
                            all_ok = False
                            break
                        if not _compare_median(got["median_impressions"], exp["median_impressions"]):
                            all_ok = False
                            break
                        if not _compare_float(got["mean_ctr"], exp["mean_ctr"], tol=1e-4):
                            all_ok = False
                            break
                    if all_ok:
                        scores["aggregates_by_topic_header_and_values"] = 1.0

    if agg_channel_path.exists() and expected_by_channel is not None:
        if _headers_match_exact(agg_channel_path, expected_agg_channel_headers):
            loaded_channel_aggs = _load_aggregates_csv(agg_channel_path, "channel")
            if loaded_channel_aggs is not None:
                if set(loaded_channel_aggs.keys()) == set(expected_by_channel.keys()):
                    all_ok = True
                    for ch, exp in expected_by_channel.items():
                        got = loaded_channel_aggs.get(ch)
                        if got is None:
                            all_ok = False
                            break
                        if got["posts_count"] != exp["posts_count"]:
                            all_ok = False
                            break
                        if not _compare_float(got["mean_engagement_rate"], exp["mean_engagement_rate"], tol=1e-4):
                            all_ok = False
                            break
                        if not _compare_median(got["median_impressions"], exp["median_impressions"]):
                            all_ok = False
                            break
                        if not _compare_float(got["mean_ctr"], exp["mean_ctr"], tol=1e-4):
                            all_ok = False
                            break
                    if all_ok:
                        scores["aggregates_by_channel_header_and_values"] = 1.0

    if rank_topics_path.exists() and expected_by_topic is not None:
        if _headers_match_exact(rank_topics_path, expected_rank_topics_headers):
            loaded_rank_topics = _load_rankings_csv(rank_topics_path, "topic_tag")
            if loaded_rank_topics is not None:
                expected_sorted = _sort_ranking_from_aggs(expected_by_topic)
                if len(loaded_rank_topics) == len(expected_sorted):
                    all_ok = True
                    for idx, (topic, metrics) in enumerate(expected_sorted):
                        row = loaded_rank_topics[idx]
                        if row["topic_tag"] != topic:
                            all_ok = False
                            break
                        if row["rank"] != idx + 1:
                            all_ok = False
                            break
                        if not _compare_float(row["mean_engagement_rate"], metrics["mean_engagement_rate"], tol=1e-4):
                            all_ok = False
                            break
                        if not _compare_median(row["median_impressions"], metrics["median_impressions"]):
                            all_ok = False
                            break
                        if row["posts_count"] != metrics["posts_count"]:
                            all_ok = False
                            break
                    if all_ok:
                        scores["rankings_topics_header_and_order"] = 1.0

    if rank_channels_path.exists() and expected_by_channel is not None:
        if _headers_match_exact(rank_channels_path, expected_rank_channels_headers):
            loaded_rank_channels = _load_rankings_csv(rank_channels_path, "channel")
            if loaded_rank_channels is not None:
                expected_sorted_channels = _sort_ranking_from_aggs(expected_by_channel)
                if len(loaded_rank_channels) == len(expected_sorted_channels):
                    all_ok = True
                    for idx, (channel, metrics) in enumerate(expected_sorted_channels):
                        row = loaded_rank_channels[idx]
                        if row["channel"] != channel:
                            all_ok = False
                            break
                        if row["rank"] != idx + 1:
                            all_ok = False
                            break
                        if not _compare_float(row["mean_engagement_rate"], metrics["mean_engagement_rate"], tol=1e-4):
                            all_ok = False
                            break
                        if not _compare_median(row["median_impressions"], metrics["median_impressions"]):
                            all_ok = False
                            break
                        if row["posts_count"] != metrics["posts_count"]:
                            all_ok = False
                            break
                    if all_ok:
                        scores["rankings_channels_header_and_order"] = 1.0

    if expected_by_topic is not None and agg_topic_path.exists():
        loaded_topic_aggs = _load_aggregates_csv(agg_topic_path, "topic_tag")
        if loaded_topic_aggs is not None:
            sample_topic = "Myofascial Release"
            exp = expected_by_topic.get(sample_topic)
            got = loaded_topic_aggs.get(sample_topic)
            if exp is not None and got is not None:
                if _compare_float(exp["mean_engagement_rate"], got["mean_engagement_rate"], tol=1e-4):
                    scores["sample_topic_metric_consistency"] = 1.0

    research = _read_json(research_notes_path)
    plan_rows = _read_content_plan(plan_path) if plan_path.exists() else None
    skeleton_rows = _read_calendar_skeleton(calendar_skeleton_path) if calendar_skeleton_path.exists() else None

    header_ok = False
    slots_ok = False
    if plan_path.exists():
        header_ok = _headers_match_exact(plan_path, expected_plan_headers)
    if header_ok and plan_rows is not None and skeleton_rows is not None:
        def tup(row: Dict[str, Any]) -> Tuple[str, str, str, str]:
            return (
                str(row.get("date", "")).strip(),
                str(row.get("channel", "")).strip(),
                str(row.get("slot_time", "")).strip(),
                str(row.get("preferred_format", "")).strip(),
            )

        plan_set = [tup(r) for r in plan_rows]
        skel_set = [tup(r) for r in skeleton_rows]
        if len(plan_set) == len(skel_set) and set(plan_set) == set(skel_set):
            slots_ok = True
    if header_ok and slots_ok:
        scores["content_plan_header_and_slots_match_skeleton"] = 1.0

    if plan_rows is not None and header_ok:
        seen = set()
        dup = False
        for r in plan_rows:
            k = (str(r.get("date", "")).strip(), str(r.get("channel", "")).strip())
            if k in seen:
                dup = True
                break
            seen.add(k)
        if not dup:
            scores["content_plan_no_duplicate_date_channel"] = 1.0

    if research is not None and plan_rows is not None and header_ok:
        focus_topics = set(research.get("focus_topics", []))
        supporting_topics = set(research.get("supporting_topics", []))
        excluded_topics = set(research.get("excluded_topics", []))
        allowed_topics = (focus_topics | supporting_topics) - excluded_topics
        prioritized_goals = list(research.get("prioritized_goals", []))
        cta_options = research.get("cta_options", {})

        topics_ok = True
        total = len(plan_rows)
        focus_count = 0
        for r in plan_rows:
            topic = str(r.get("topic_tag", "")).strip()
            if topic in focus_topics:
                focus_count += 1
            if topic not in allowed_topics:
                topics_ok = False
                break
        if topics_ok and total > 0:
            scores["content_plan_topics_allowed"] = 1.0

        if total > 0:
            frac = focus_count / total
            if frac >= 0.75:
                scores["content_plan_focus_topics_fraction"] = 1.0

        goal_cta_ok = True
        for r in plan_rows:
            goal = str(r.get("goal", "")).strip()
            channel = str(r.get("channel", "")).strip()
            cta = str(r.get("cta", "")).strip()
            valid_goals = prioritized_goals
            valid_ctas = cta_options.get(channel, [])
            if goal not in valid_goals:
                goal_cta_ok = False
                break
            if cta not in valid_ctas:
                goal_cta_ok = False
                break
        if goal_cta_ok:
            scores["content_plan_goals_and_ctas_valid"] = 1.0

        top_topic: Optional[str] = None
        if rank_topics_path.exists() and _headers_match_exact(rank_topics_path, expected_rank_topics_headers):
            rank_rows = _read_csv_dicts(rank_topics_path)
            if rank_rows and "topic_tag" in rank_rows[0]:
                top_topic = str(rank_rows[0].get("topic_tag", "")).strip()
        if top_topic:
            by_week: Dict[int, int] = {}
            for r in plan_rows:
                date_str = str(r.get("date", "")).strip()
                wk = _iso_week(date_str)
                if wk is None:
                    continue
                by_week.setdefault(wk, 0)
            weekly_ok = True
            for r in plan_rows:
                date_str = str(r.get("date", "")).strip()
                wk = _iso_week(date_str)
                if wk is None:
                    continue
                topic = str(r.get("topic_tag", "")).strip()
                if topic == top_topic:
                    by_week[wk] = by_week.get(wk, 0) + 1
            for wk in by_week:
                if by_week[wk] < 1:
                    weekly_ok = False
                    break
            if weekly_ok and len(by_week) > 0:
                scores["content_plan_top_topic_weekly"] = 1.0

    if val_report_path.exists():
        try:
            content = val_report_path.read_text(encoding="utf-8")
            if content.strip():
                scores["validation_report_present"] = 1.0
        except Exception:
            pass

    if val_summary_path.exists():
        summary = _read_json(val_summary_path)
        if isinstance(summary, dict):
            tests_run = summary.get("tests_run")
            tests_failed = summary.get("tests_failed")
            status = summary.get("status")
            if isinstance(tests_run, int) and isinstance(tests_failed, int) and isinstance(status, str):
                if status.lower() == "passed" and tests_failed == 0 and tests_run >= 1:
                    scores["validation_summary_passed"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()