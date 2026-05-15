import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    records = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                records.append(obj)
            else:
                return None
        except Exception:
            return None
    return records


def _safe_read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _load_stopwords(path: Path) -> Optional[set]:
    txt = _safe_read_text(path)
    if txt is None:
        return None
    words = set()
    for line in txt.splitlines():
        w = line.strip().lower()
        if w:
            words.add(w)
    return words


def _tokenize(text: str, stopwords: set) -> List[str]:
    t = text.lower()
    t = re.sub(r"[^a-z]+", " ", t)
    tokens = [tok for tok in t.split() if len(tok) >= 3 and tok not in stopwords]
    return tokens


def _compute_weekly_expected(
    logs_path: Path, activities_path: Path, stopwords_path: Path
) -> Optional[Dict[str, dict]]:
    logs = _safe_read_jsonl(logs_path)
    if logs is None:
        return None
    rows = _safe_read_csv_rows(activities_path)
    if rows is None:
        return None
    stopwords = _load_stopwords(stopwords_path)
    if stopwords is None:
        return None

    activity_to_category: Dict[str, str] = {}
    for r in rows:
        act = (r.get("activity") or "").strip()
        cat = (r.get("category") or "").strip()
        if act and cat:
            activity_to_category[act] = cat

    weekly = {}
    for rec in logs:
        date_str = rec.get("date")
        d = _parse_iso_date(date_str) if isinstance(date_str, str) else None
        if d is None:
            return None
        week_start = _monday_of_week(d)
        ws_key = week_start.isoformat()
        w = weekly.setdefault(
            ws_key,
            {
                "count": 0,
                "sum_mood": 0.0,
                "sum_anxiety": 0.0,
                "sum_duration": 0.0,
                "category_counts": {},
                "tag_counts": {},
                "keyword_counts": {},
                "nature_count": 0,
            },
        )
        try:
            mood = float(rec.get("mood"))
            anx = float(rec.get("anxiety"))
            dur = float(rec.get("duration_minutes"))
        except Exception:
            return None
        w["count"] += 1
        w["sum_mood"] += mood
        w["sum_anxiety"] += anx
        w["sum_duration"] += dur

        activity = rec.get("activity")
        if isinstance(activity, str):
            cat = activity_to_category.get(activity)
            if cat:
                w["category_counts"][cat] = w["category_counts"].get(cat, 0) + 1

        tags = rec.get("tags")
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, str):
                    tag = t.strip().lower()
                    if not tag:
                        continue
                    w["tag_counts"][tag] = w["tag_counts"].get(tag, 0) + 1
                    if tag == "nature":
                        w["nature_count"] += 1
        else:
            if tags is not None:
                return None

        notes = rec.get("notes")
        if isinstance(notes, str):
            tokens = _tokenize(notes, stopwords)
            for tok in tokens:
                w["keyword_counts"][tok] = w["keyword_counts"].get(tok, 0) + 1
        elif notes is not None:
            return None

    expected = {}
    for ws in sorted(weekly.keys()):
        w = weekly[ws]
        cnt = w["count"]
        if cnt <= 0:
            avg_mood = 0.0
            avg_anxiety = 0.0
            avg_duration = 0.0
        else:
            avg_mood = w["sum_mood"] / cnt
            avg_anxiety = w["sum_anxiety"] / cnt
            avg_duration = w["sum_duration"] / cnt

        dom_cat = None
        if w["category_counts"]:
            max_count = max(w["category_counts"].values())
            tied = sorted([c for c, n in w["category_counts"].items() if n == max_count])
            dom_cat = tied[0] if tied else None

        top_tags = []
        if w["tag_counts"]:
            items = list(w["tag_counts"].items())
            items.sort(key=lambda x: (-x[1], x[0]))
            top_tags = [t for t, c in items[:3]]

        top_keywords = []
        if w["keyword_counts"]:
            kitems = list(w["keyword_counts"].items())
            kitems.sort(key=lambda x: (-x[1], x[0]))
            top_keywords = [k for k, c in kitems[:5]]

        expected[ws] = {
            "week_start": ws,
            "sessions": cnt,
            "avg_mood": avg_mood,
            "avg_anxiety": avg_anxiety,
            "avg_duration_minutes": avg_duration,
            "dominant_activity_category": dom_cat,
            "top_tags": top_tags,
            "top_keywords": top_keywords,
            "nature_count": w["nature_count"],
            "keyword_counts": w["keyword_counts"],
        }
    return expected


def _compute_keyword_trends_expected(weekly_expected: Dict[str, dict]) -> List[Tuple[str, str, int]]:
    rows = []
    for ws in sorted(weekly_expected.keys()):
        kc = weekly_expected[ws].get("keyword_counts", {})
        for kw, count in kc.items():
            if count >= 2:
                rows.append((ws, kw, int(count)))
    rows.sort(key=lambda r: (r[0], -r[2], r[1]))
    return rows


def _float_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_weekly_metrics(path: Path) -> Optional[List[dict]]:
    data = _safe_read_json(path)
    if not isinstance(data, list):
        return None
    return data


def _check_sorted_by_week_start(data: List[dict]) -> bool:
    prev = None
    for obj in data:
        ws = obj.get("week_start")
        if not isinstance(ws, str):
            return False
        try:
            d = date.fromisoformat(ws)
        except Exception:
            return False
        if prev is not None and d < prev:
            return False
        prev = d
    return True


def _compute_slopes_from_expected(weekly_expected: Dict[str, dict]) -> Tuple[float, float, List[str]]:
    week_starts = sorted(weekly_expected.keys())
    y_mood = [weekly_expected[ws]["avg_mood"] for ws in week_starts]
    y_anx = [weekly_expected[ws]["avg_anxiety"] for ws in week_starts]
    n = len(week_starts)
    if n == 0:
        return (0.0, 0.0, [])
    x_vals = list(range(n))
    x_mean = sum(x_vals) / n

    def slope(y_vals: List[float]) -> float:
        y_mean = sum(y_vals) / n
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
        den = sum((x - x_mean) ** 2 for x in x_vals)
        return 0.0 if den == 0 else num / den

    return (slope(y_mood), slope(y_anx), week_starts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "weekly_metrics_structure": 0.0,
        "weekly_metrics_values": 0.0,
        "keyword_trends_structure": 0.0,
        "keyword_trends_values": 0.0,
        "report_slopes_and_classification": 0.0,
        "report_nature_counts": 0.0,
        "run_command_present": 0.0,
    }

    logs_path = workspace / "input" / "session_logs.jsonl"
    activities_path = workspace / "input" / "art_activities.csv"
    stopwords_path = workspace / "input" / "stopwords.txt"

    expected_weekly = _compute_weekly_expected(logs_path, activities_path, stopwords_path)
    if expected_weekly is None:
        expected_keyword_trends = []
    else:
        expected_keyword_trends = _compute_keyword_trends_expected(expected_weekly)

    weekly_metrics_path = workspace / "output" / "weekly_metrics.json"
    weekly_data = _parse_weekly_metrics(weekly_metrics_path) if weekly_metrics_path.exists() else None

    if weekly_data is not None and isinstance(weekly_data, list) and len(weekly_data) >= 0:
        structure_ok = True
        if not _check_sorted_by_week_start(weekly_data):
            structure_ok = False
        required_keys = {
            "week_start",
            "sessions",
            "avg_mood",
            "avg_anxiety",
            "avg_duration_minutes",
            "dominant_activity_category",
            "top_tags",
            "top_keywords",
        }
        for obj in weekly_data:
            if not isinstance(obj, dict):
                structure_ok = False
                break
            if not required_keys.issubset(set(obj.keys())):
                structure_ok = False
                break
            if not isinstance(obj.get("week_start"), str):
                structure_ok = False
                break
            if not isinstance(obj.get("sessions"), (int, float)):
                structure_ok = False
                break
            if not isinstance(obj.get("avg_mood"), (int, float)):
                structure_ok = False
                break
            if not isinstance(obj.get("avg_anxiety"), (int, float)):
                structure_ok = False
                break
            if not isinstance(obj.get("avg_duration_minutes"), (int, float)):
                structure_ok = False
                break
            if obj.get("dominant_activity_category") is not None and not isinstance(obj.get("dominant_activity_category"), str):
                structure_ok = False
                break
            if not isinstance(obj.get("top_tags"), list):
                structure_ok = False
                break
            if not isinstance(obj.get("top_keywords"), list):
                structure_ok = False
                break

        if expected_weekly is not None:
            if len(weekly_data) != len(expected_weekly):
                structure_ok = False
            else:
                got_weeks = [o.get("week_start") for o in weekly_data]
                if got_weeks != sorted(expected_weekly.keys()):
                    structure_ok = False

        if structure_ok:
            scores["weekly_metrics_structure"] = 1.0

        if expected_weekly is not None and structure_ok:
            values_ok = True
            for obj in weekly_data:
                ws = obj["week_start"]
                exp = expected_weekly.get(ws)
                if exp is None:
                    values_ok = False
                    break
                if int(obj["sessions"]) != int(exp["sessions"]):
                    values_ok = False
                    break
                if not _float_close(float(obj["avg_mood"]), float(exp["avg_mood"]), tol=1e-6):
                    values_ok = False
                    break
                if not _float_close(float(obj["avg_anxiety"]), float(exp["avg_anxiety"]), tol=1e-6):
                    values_ok = False
                    break
                if not _float_close(float(obj["avg_duration_minutes"]), float(exp["avg_duration_minutes"]), tol=1e-6):
                    values_ok = False
                    break
                if exp["dominant_activity_category"] != obj.get("dominant_activity_category"):
                    if not (exp["dominant_activity_category"] is None and obj.get("dominant_activity_category") is None):
                        values_ok = False
                        break
                got_tags = obj.get("top_tags")
                if not isinstance(got_tags, list):
                    values_ok = False
                    break
                if [str(t).lower() for t in got_tags] != exp["top_tags"]:
                    values_ok = False
                    break
                got_keywords = obj.get("top_keywords")
                if not isinstance(got_keywords, list):
                    values_ok = False
                    break
                if [str(k).lower() for k in got_keywords] != exp["top_keywords"]:
                    values_ok = False
                    break
            if values_ok:
                scores["weekly_metrics_values"] = 1.0

    trends_path = workspace / "output" / "keyword_trends.csv"
    trends_rows = None
    if trends_path.exists():
        try:
            with trends_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows_all = list(reader)
        except Exception:
            rows_all = None
        if rows_all is not None and len(rows_all) >= 1:
            header = rows_all[0]
            if header == ["week_start", "keyword", "count"]:
                tr_ok = True
                parsed = []
                for r in rows_all[1:]:
                    if len(r) != 3:
                        tr_ok = False
                        break
                    ws, kw, count = r
                    try:
                        date.fromisoformat(ws)
                    except Exception:
                        tr_ok = False
                        break
                    try:
                        cnt_int = int(count)
                    except Exception:
                        tr_ok = False
                        break
                    parsed.append((ws, kw, cnt_int))
                if tr_ok:
                    sorted_check = sorted(parsed, key=lambda x: (x[0], -x[2], x[1]))
                    if parsed == sorted_check:
                        scores["keyword_trends_structure"] = 1.0
                        trends_rows = parsed

    if expected_weekly is not None and scores["keyword_trends_structure"] == 1.0 and trends_rows is not None:
        expected_trends = _compute_keyword_trends_expected(expected_weekly)
        if trends_rows == expected_trends:
            scores["keyword_trends_values"] = 1.0

    report_path = workspace / "output" / "report.md"
    report_text = _safe_read_text(report_path) if report_path.exists() else None
    if expected_weekly is not None and report_text is not None:
        slope_mood, slope_anx, week_order = _compute_slopes_from_expected(expected_weekly)
        slope_mood_str = f"{round(slope_mood + 0.0, 2):.2f}"
        slope_anx_str = f"{round(slope_anx + 0.0, 2):.2f}"

        if slope_mood >= 0.10:
            mood_class = "Improving"
        elif slope_mood <= -0.10:
            mood_class = "Declining"
        else:
            mood_class = "Stable"

        if slope_anx <= -0.10:
            anx_class = "Improving"
        elif slope_anx >= 0.10:
            anx_class = "Declining"
        else:
            anx_class = "Stable"

        slopes_ok = (slope_mood_str in report_text) and (slope_anx_str in report_text)
        class_ok = ("Mood trend: " + mood_class) in report_text and ("Anxiety trend: " + anx_class) in report_text
        if slopes_ok and class_ok:
            scores["report_slopes_and_classification"] = 1.0

        nature_ok = True
        for ws in week_order:
            nature_count = expected_weekly[ws]["nature_count"]
            bullet_line = f"- {ws}: nature_count={nature_count}"
            if bullet_line not in report_text:
                nature_ok = False
                break
        if nature_ok:
            scores["report_nature_counts"] = 1.0

    run_cmd_path = workspace / "output" / "run_command.txt"
    run_cmd_txt = _safe_read_text(run_cmd_path)
    if run_cmd_txt is not None:
        first_line = run_cmd_txt.splitlines()[0].strip() if run_cmd_txt.splitlines() else ""
        if len(first_line) > 0:
            scores["run_command_present"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()