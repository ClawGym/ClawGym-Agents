import json
import sys
import csv
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_iso_date(s: str) -> Optional[datetime.date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _safe_parse_discussions_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            expected = ["date", "topic", "issue", "sentiment", "conversations"]
            if reader.fieldnames is None:
                return None
            for col in expected:
                if col not in reader.fieldnames:
                    return None
            for r in reader:
                d = _parse_iso_date(r.get("date", "").strip())
                if d is None:
                    return None
                topic = r.get("topic", "").strip()
                issue = r.get("issue", "").strip()
                try:
                    sentiment = float(str(r.get("sentiment", "")).strip())
                except Exception:
                    return None
                try:
                    conversations = int(str(r.get("conversations", "")).strip())
                except Exception:
                    return None
                rows.append(
                    {
                        "date": d,
                        "topic": topic,
                        "issue": issue,
                        "sentiment": sentiment,
                        "conversations": conversations,
                    }
                )
        return rows
    except Exception:
        return None


def _compute_window(rows: List[Dict[str, Any]]) -> Optional[Tuple[datetime.date, datetime.date, List[Dict[str, Any]]]]:
    if not rows:
        return None
    max_date = max(r["date"] for r in rows)
    start_date = max_date - timedelta(days=6)
    window_rows = [r for r in rows if start_date <= r["date"] <= max_date]
    if not window_rows:
        return None
    return start_date, max_date, window_rows


def _round(value: float, ndigits: int) -> float:
    return round(value + 1e-12, ndigits)


def _compute_aggregates(window_rows: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, float]], int]:
    per_topic: Dict[str, Dict[str, Any]] = {}
    for r in window_rows:
        t = r["topic"]
        if t not in per_topic:
            per_topic[t] = {"sentiments": [], "conversations": 0}
        per_topic[t]["sentiments"].append(r["sentiment"])
        per_topic[t]["conversations"] += r["conversations"]
    total_conversations = sum(pt["conversations"] for pt in per_topic.values())
    result: Dict[str, Dict[str, float]] = {}
    for t, data in per_topic.items():
        avg_sent = sum(data["sentiments"]) / len(data["sentiments"])
        avg_sent = _round(avg_sent, 2)
        share = (data["conversations"] / total_conversations * 100.0) if total_conversations > 0 else 0.0
        share = _round(share, 1)
        result[t] = {
            "total_conversations": int(data["conversations"]),
            "avg_sentiment": float(avg_sent),
            "share_of_total": float(share),
        }
    return result, total_conversations


def _compute_ranking(agg: Dict[str, Dict[str, float]]) -> List[Tuple[str, int, float]]:
    items = [(t, int(v["total_conversations"]), float(v["avg_sentiment"])) for t, v in agg.items()]
    items.sort(key=lambda x: (-x[1], -x[2]))
    return items


def _parse_topic_summary_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            expected_header = ["topic", "total_conversations", "avg_sentiment", "rank_by_conversations"]
            if [h.strip() for h in reader.fieldnames] != expected_header:
                return None
            rows: List[Dict[str, Any]] = []
            for r in reader:
                topic = r.get("topic", "").strip()
                try:
                    total_conversations = int(str(r.get("total_conversations", "")).strip())
                    avg_sentiment = float(str(r.get("avg_sentiment", "")).strip())
                    rank_by_conversations = int(str(r.get("rank_by_conversations", "")).strip())
                except Exception:
                    return None
                rows.append(
                    {
                        "topic": topic,
                        "total_conversations": total_conversations,
                        "avg_sentiment": avg_sentiment,
                        "rank_by_conversations": rank_by_conversations,
                    }
                )
            return rows
    except Exception:
        return None


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _int_present(n: int, text: str) -> bool:
    pattern = r"\b" + re.escape(str(n)) + r"\b"
    return re.search(pattern, text) is not None


def _contains_exact_once(text: str, sub: str) -> bool:
    return text.count(sub) == 1


def _find_peak_day_line(text: str) -> Optional[Tuple[str, int]]:
    for line in text.splitlines():
        m = re.match(r"^\s*Peak day:\s*(\d{4}-\d{2}-\d{2})\s*\((\d+)\s+conversations\)\s*$", line)
        if m:
            return m.group(1), int(m.group(2))
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "stats_json_exists": 0.0,
        "stats_json_structure_valid": 0.0,
        "stats_json_window_and_total_correct": 0.0,
        "stats_json_topics_values_correct": 0.0,
        "topic_summary_csv_exists": 0.0,
        "topic_summary_header_valid": 0.0,
        "topic_summary_values_and_ranks_correct": 0.0,
        "post_final_exists": 0.0,
        "post_final_word_count_120_180": 0.0,
        "post_final_includes_top3_topics_and_counts_and_total": 0.0,
        "post_final_includes_cta_verbatim_once": 0.0,
        "post_final_no_placeholders": 0.0,
        "weekly_notes_exists": 0.0,
        "weekly_notes_word_count_100_150": 0.0,
        "weekly_notes_includes_top3_topics_and_counts": 0.0,
        "weekly_notes_peak_day_line_correct": 0.0,
    }

    input_csv_path = workspace / "input" / "discussions.csv"
    cta_path = workspace / "input" / "cta.txt"
    stats_json_path = workspace / "output" / "stats.json"
    topic_summary_csv_path = workspace / "output" / "topic_summary.csv"
    post_final_path = workspace / "output" / "post_final.md"
    weekly_notes_path = workspace / "output" / "weekly_notes.md"

    rows = _safe_parse_discussions_csv(input_csv_path)
    expected_start_date: Optional[datetime.date] = None
    expected_end_date: Optional[datetime.date] = None
    expected_window_rows: Optional[List[Dict[str, Any]]] = None
    expected_agg: Optional[Dict[str, Dict[str, float]]] = None
    expected_total: Optional[int] = None
    expected_ranking: Optional[List[Tuple[str, int, float]]] = None
    expected_top3: List[Tuple[str, int]] = []
    expected_daily_totals: Dict[str, int] = {}

    if rows is not None:
        window = _compute_window(rows)
        if window is not None:
            expected_start_date, expected_end_date, expected_window_rows = window
            expected_agg, expected_total = _compute_aggregates(expected_window_rows)
            expected_ranking = _compute_ranking(expected_agg)
            expected_top3 = [(t, tc) for (t, tc, _as) in expected_ranking[:3]]
            for r in expected_window_rows:
                d = r["date"].isoformat()
                expected_daily_totals[d] = expected_daily_totals.get(d, 0) + r["conversations"]

    if stats_json_path.exists():
        scores["stats_json_exists"] = 1.0
        stats_obj = _safe_load_json(stats_json_path)
        if isinstance(stats_obj, dict):
            window_obj = stats_obj.get("window", {})
            has_struct = (
                isinstance(window_obj, dict)
                and "start_date" in window_obj
                and "end_date" in window_obj
                and "total_conversations" in stats_obj
                and "topics" in stats_obj
                and isinstance(stats_obj.get("topics"), list)
            )
            if has_struct:
                scores["stats_json_structure_valid"] = 1.0
                if expected_start_date is not None and expected_end_date is not None and expected_total is not None:
                    sd = window_obj.get("start_date")
                    ed = window_obj.get("end_date")
                    total = stats_obj.get("total_conversations")
                    if (
                        isinstance(sd, str)
                        and isinstance(ed, str)
                        and sd == expected_start_date.isoformat()
                        and ed == expected_end_date.isoformat()
                        and isinstance(total, int)
                        and total == expected_total
                    ):
                        scores["stats_json_window_and_total_correct"] = 1.0
                if expected_agg is not None:
                    topics_list = stats_obj.get("topics", [])
                    ok_topics = True
                    got: Dict[str, Dict[str, Any]] = {}
                    try:
                        for t in topics_list:
                            topic_name = t.get("topic", "")
                            got[topic_name] = t
                    except Exception:
                        ok_topics = False
                    if ok_topics:
                        if set(got.keys()) != set(expected_agg.keys()):
                            ok_topics = False
                        else:
                            for topic, vals in expected_agg.items():
                                g = got.get(topic)
                                if g is None:
                                    ok_topics = False
                                    break
                                try:
                                    g_total = int(g.get("total_conversations"))
                                    g_avg = float(g.get("avg_sentiment"))
                                    g_share = float(g.get("share_of_total"))
                                except Exception:
                                    ok_topics = False
                                    break
                                if not (
                                    g_total == int(vals["total_conversations"])
                                    and _round(g_avg, 2) == vals["avg_sentiment"]
                                    and _round(g_share, 1) == vals["share_of_total"]
                                ):
                                    ok_topics = False
                                    break
                    if ok_topics:
                        scores["stats_json_topics_values_correct"] = 1.0

    if topic_summary_csv_path.exists():
        scores["topic_summary_csv_exists"] = 1.0
        parsed_summary = _parse_topic_summary_csv(topic_summary_csv_path)
        if parsed_summary is not None:
            scores["topic_summary_header_valid"] = 1.0
            if expected_agg is not None and expected_ranking is not None:
                exp_vals: Dict[str, Dict[str, Any]] = {}
                for idx, (t, tot, avg) in enumerate(expected_ranking, start=1):
                    exp_vals[t] = {
                        "total_conversations": tot,
                        "avg_sentiment": _round(avg, 2),
                        "rank_by_conversations": idx,
                    }
                ok_values = True
                if set([r["topic"] for r in parsed_summary]) != set(exp_vals.keys()):
                    ok_values = False
                else:
                    for row in parsed_summary:
                        t = row["topic"]
                        ev = exp_vals.get(t)
                        if ev is None:
                            ok_values = False
                            break
                        try:
                            if not (
                                int(row["total_conversations"]) == int(ev["total_conversations"])
                                and _round(float(row["avg_sentiment"]), 2) == ev["avg_sentiment"]
                                and int(row["rank_by_conversations"]) == int(ev["rank_by_conversations"])
                            ):
                                ok_values = False
                                break
                        except Exception:
                            ok_values = False
                            break
                if ok_values:
                    scores["topic_summary_values_and_ranks_correct"] = 1.0

    if post_final_path.exists():
        scores["post_final_exists"] = 1.0
        post_text = _safe_read_text(post_final_path) or ""
        wc = _word_count(post_text)
        if 120 <= wc <= 180:
            scores["post_final_word_count_120_180"] = 1.0
        cta_text = (_safe_read_text(cta_path) or "").strip("\n\r")
        if cta_text and _contains_exact_once(post_text, cta_text):
            scores["post_final_includes_cta_verbatim_once"] = 1.0
        if "[[" not in post_text and "]]" not in post_text:
            scores["post_final_no_placeholders"] = 1.0
        if expected_top3 and expected_total is not None:
            ok_mentions = True
            for (topic, count) in expected_top3:
                if re.search(re.escape(topic), post_text, flags=re.IGNORECASE) is None or not _int_present(count, post_text):
                    ok_mentions = False
                    break
            if ok_mentions and _int_present(expected_total, post_text):
                scores["post_final_includes_top3_topics_and_counts_and_total"] = 1.0

    if weekly_notes_path.exists():
        scores["weekly_notes_exists"] = 1.0
        notes_text = _safe_read_text(weekly_notes_path) or ""
        wc_notes = _word_count(notes_text)
        if 100 <= wc_notes <= 150:
            scores["weekly_notes_word_count_100_150"] = 1.0
        if expected_top3:
            ok_notes_topics = True
            for (topic, count) in expected_top3:
                if re.search(re.escape(topic), notes_text, flags=re.IGNORECASE) is None or not _int_present(count, notes_text):
                    ok_notes_topics = False
                    break
            if ok_notes_topics:
                scores["weekly_notes_includes_top3_topics_and_counts"] = 1.0
        if expected_daily_totals:
            peak_info = _find_peak_day_line(notes_text)
            if peak_info is not None:
                date_str, n_conv = peak_info
                if date_str in expected_daily_totals:
                    max_val = max(expected_daily_totals.values())
                    if expected_daily_totals[date_str] == n_conv and n_conv == max_val:
                        scores["weekly_notes_peak_day_line_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()