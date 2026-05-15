import csv
import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dict(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames if reader.fieldnames is not None else []
            return (headers, rows)
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                records.append(json.loads(s))
        return records
    except Exception:
        return None


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def _round3(x: float) -> float:
    return round(x + 1e-12, 3)


def _to_float_safe(s: Any) -> Optional[float]:
    try:
        if isinstance(s, (int, float)):
            return float(s)
        return float(str(s).strip())
    except Exception:
        return None


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    submissions_path = workspace / "input" / "submissions.csv"
    reviews_path = workspace / "input" / "reviews.jsonl"
    config_path = workspace / "input" / "config.json"

    cfg = _safe_load_json(config_path)
    csv_data = _safe_read_csv_dict(submissions_path)
    jsonl_data = _safe_read_jsonl(reviews_path)
    if cfg is None or csv_data is None or jsonl_data is None:
        return None

    headers, sub_rows = csv_data
    required_sub_cols = {"manuscript_id", "title", "author", "topic"}
    if not required_sub_cols.issubset(set(headers)):
        return None

    filter_topic = cfg.get("filter_topic_contains")
    weights = cfg.get("weights", {})
    try:
        avg_w = float(weights.get("avg_score_weight"))
        acc_w = float(weights.get("accept_rate_weight"))
        acc_scale = float(weights.get("accept_rate_scale"))
    except Exception:
        return None
    if filter_topic is None:
        return None

    submissions: Dict[str, Dict[str, str]] = {}
    for r in sub_rows:
        mid = r.get("manuscript_id", "")
        if mid:
            submissions[mid] = r

    reviews_by_mid: Dict[str, List[Dict[str, Any]]] = {}
    for rec in jsonl_data:
        mid = rec.get("manuscript_id")
        if mid is None:
            continue
        reviews_by_mid.setdefault(mid, []).append(rec)

    filtered_ids: List[str] = []
    for mid, sub in submissions.items():
        topic = sub.get("topic", "")
        if filter_topic.lower() in topic.lower():
            filtered_ids.append(mid)

    considered_ids: List[str] = [mid for mid in filtered_ids if mid in reviews_by_mid and len(reviews_by_mid[mid]) > 0]

    per_mid: Dict[str, Dict[str, Any]] = {}
    total_reviews_considered = 0
    total_score_sum = 0.0
    total_accepts = 0

    for mid in considered_ids:
        recs = reviews_by_mid.get(mid, [])
        if not recs:
            continue
        scores = []
        accepts = 0
        latest_dt: Optional[datetime] = None
        for rec in recs:
            sc = _to_float_safe(rec.get("score"))
            if sc is None:
                return None
            scores.append(sc)
            decision = str(rec.get("decision", "")).strip().lower()
            if decision == "accept":
                accepts += 1
            rd = str(rec.get("review_date", "")).strip()
            dt = _parse_date(rd)
            if dt is None:
                return None
            if latest_dt is None or dt > latest_dt:
                latest_dt = dt
        if latest_dt is None:
            return None
        avg_score_raw = sum(scores) / len(scores)
        accept_rate_raw = accepts / len(scores)
        latest_review_date = latest_dt.strftime("%Y-%m-%d")
        composite_raw = (avg_w * avg_score_raw) + (acc_w * (accept_rate_raw * acc_scale))

        per_mid[mid] = {
            "avg_score_raw": avg_score_raw,
            "avg_score": _round3(avg_score_raw),
            "accept_rate_raw": accept_rate_raw,
            "accept_rate": _round3(accept_rate_raw),
            "latest_review_date": latest_review_date,
            "composite_raw": composite_raw,
            "composite_score": _round3(composite_raw),
            "title": submissions[mid].get("title", ""),
            "author": submissions[mid].get("author", ""),
        }

        total_reviews_considered += len(scores)
        total_score_sum += sum(scores)
        total_accepts += accepts

    def sort_key(mid: str):
        m = per_mid[mid]
        comp = m["composite_raw"]
        dt = _parse_date(m["latest_review_date"])
        dt_key = dt.timestamp() if dt else 0.0
        return (-comp, -dt_key, mid)

    sorted_ids = sorted(per_mid.keys(), key=sort_key)

    expected_rows: List[Dict[str, Any]] = []
    for i, mid in enumerate(sorted_ids, start=1):
        m = per_mid[mid]
        expected_rows.append({
            "manuscript_id": mid,
            "title": m["title"],
            "author": m["author"],
            "avg_score": m["avg_score"],
            "accept_rate": m["accept_rate"],
            "latest_review_date": m["latest_review_date"],
            "composite_score": m["composite_score"],
            "rank": i,
        })

    overall_avg = _round3(total_score_sum / total_reviews_considered) if total_reviews_considered > 0 else 0.0
    overall_accept_rate = _round3(total_accepts / total_reviews_considered) if total_reviews_considered > 0 else 0.0
    top3 = [r["manuscript_id"] for r in expected_rows[:3]]

    author_map: Dict[str, List[float]] = {}
    for mid in sorted_ids:
        author = per_mid[mid]["author"]
        author_map.setdefault(author, []).append(per_mid[mid]["avg_score_raw"])
    author_stats: List[Tuple[str, float]] = []
    for author, vals in author_map.items():
        if not vals:
            continue
        author_avg = _round3(sum(vals) / len(vals))
        author_stats.append((author, author_avg))
    author_stats_sorted = sorted(author_stats, key=lambda x: (-x[1], x[0]))
    authors_ranked = [{"author": a, "avg_score": s} for a, s in author_stats_sorted]

    return {
        "filter_topic": filter_topic,
        "expected_rows": expected_rows,
        "manuscripts_considered": len(expected_rows),
        "total_reviews_considered": total_reviews_considered,
        "overall_avg_score_weighted_by_reviews": overall_avg,
        "overall_accept_rate": overall_accept_rate,
        "top_3": top3,
        "authors_ranked": authors_ranked,
        "cron": str(cfg.get("schedule", {}).get("cron", "")),
    }


def _check_shortlist_csv(workspace: Path, expected: Dict[str, Any]) -> bool:
    csv_path = workspace / "output" / "weekly_shortlist.csv"
    read = _safe_read_csv_dict(csv_path)
    if read is None:
        return False
    headers, rows = read
    expected_cols = [
        "manuscript_id",
        "title",
        "author",
        "avg_score",
        "accept_rate",
        "latest_review_date",
        "composite_score",
        "rank",
    ]
    if headers != expected_cols:
        return False

    exp_rows: List[Dict[str, Any]] = expected["expected_rows"]
    if len(rows) != len(exp_rows):
        return False

    for row, exp in zip(rows, exp_rows):
        if row.get("manuscript_id") != exp["manuscript_id"]:
            return False
        if row.get("title") != exp["title"]:
            return False
        if row.get("author") != exp["author"]:
            return False
        if row.get("latest_review_date") != exp["latest_review_date"]:
            return False
        avg_f = _to_float_safe(row.get("avg_score"))
        acc_f = _to_float_safe(row.get("accept_rate"))
        comp_f = _to_float_safe(row.get("composite_score"))
        if avg_f is None or acc_f is None or comp_f is None:
            return False
        if _round3(avg_f) != exp["avg_score"]:
            return False
        if _round3(acc_f) != exp["accept_rate"]:
            return False
        if _round3(comp_f) != exp["composite_score"]:
            return False
        try:
            rank_val = int(str(row.get("rank", "")).strip())
        except Exception:
            return False
        if rank_val != exp["rank"]:
            return False

    return True


def _check_summary_json(workspace: Path, expected: Dict[str, Any]) -> bool:
    summ_path = workspace / "output" / "summary_stats.json"
    data = _safe_load_json(summ_path)
    if data is None:
        return False

    required_keys = {
        "topic_filter",
        "manuscripts_considered",
        "total_reviews_considered",
        "overall_avg_score_weighted_by_reviews",
        "overall_accept_rate",
        "top_3_by_composite",
        "authors_ranked_by_avg_score",
    }
    if not required_keys.issubset(set(data.keys())):
        return False

    if data.get("topic_filter") != expected["filter_topic"]:
        return False

    if data.get("manuscripts_considered") != expected["manuscripts_considered"]:
        return False

    if data.get("total_reviews_considered") != expected["total_reviews_considered"]:
        return False

    oavg = _to_float_safe(data.get("overall_avg_score_weighted_by_reviews"))
    if oavg is None or _round3(oavg) != expected["overall_avg_score_weighted_by_reviews"]:
        return False

    orate = _to_float_safe(data.get("overall_accept_rate"))
    if orate is None or _round3(orate) != expected["overall_accept_rate"]:
        return False

    top3 = data.get("top_3_by_composite")
    if not isinstance(top3, list):
        return False
    if top3 != expected["top_3"]:
        return False

    authors = data.get("authors_ranked_by_avg_score")
    if not isinstance(authors, list):
        return False
    exp_authors = expected["authors_ranked"]
    if len(authors) != len(exp_authors):
        return False
    for got, exp in zip(authors, exp_authors):
        if got.get("author") != exp["author"]:
            return False
        av = _to_float_safe(got.get("avg_score"))
        if av is None or _round3(av) != exp["avg_score"]:
            return False

    return True


def _check_crontab(workspace: Path, expected: Dict[str, Any]) -> bool:
    cron_file = workspace / "schedule" / "crontab.txt"
    txt = _safe_read_text(cron_file)
    if txt is None:
        return False
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip() != ""]
    if len(lines) != 1:
        return False
    cron_spec = expected.get("cron", "")
    if not cron_spec:
        return False
    expected_line = f"{cron_spec} python3 scripts/weekly_shortlist.py --input-dir input --output-dir output --config input/config.json >> logs/run.log 2>&1"
    return lines[0] == expected_line


def _check_log(workspace: Path, shortlist_rows_count: Optional[int]) -> bool:
    log_path = workspace / "logs" / "run.log"
    txt = _safe_read_text(log_path)
    if txt is None:
        return False
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip() != ""]
    if not lines:
        return False
    last = lines[-1]
    # Look for ISO-like timestamp and shortlisted count
    ts_match = re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(Z|([+-]\d{2}:\d{2}))?", last)
    count_match = re.search(r"shortlisted=(\d+)", last)
    if not ts_match or not count_match:
        return False
    try:
        count = int(count_match.group(1))
    except Exception:
        return False
    if shortlist_rows_count is not None and count != shortlist_rows_count:
        return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_file_present": 0.0,
        "crontab_single_line_correct": 0.0,
        "shortlist_csv_correct": 0.0,
        "summary_stats_json_correct": 0.0,
        "run_log_entry_present_and_valid": 0.0,
    }

    script_path = workspace / "scripts" / "weekly_shortlist.py"
    if script_path.is_file():
        scores["script_file_present"] = 1.0

    expected = _compute_expected(workspace)

    if expected is not None and _check_crontab(workspace, expected):
        scores["crontab_single_line_correct"] = 1.0

    shortlist_ok = False
    shortlist_rows_count: Optional[int] = None
    if expected is not None:
        shortlist_ok = _check_shortlist_csv(workspace, expected)
        if shortlist_ok:
            scores["shortlist_csv_correct"] = 1.0
            shortlist_rows_count = expected["manuscripts_considered"]
        else:
            csv_path = workspace / "output" / "weekly_shortlist.csv"
            read = _safe_read_csv_dict(csv_path)
            if read is not None:
                _, rows = read
                shortlist_rows_count = len(rows)

    if expected is not None and _check_summary_json(workspace, expected):
        scores["summary_stats_json_correct"] = 1.0

    if _check_log(workspace, shortlist_rows_count):
        scores["run_log_entry_present_and_valid"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()