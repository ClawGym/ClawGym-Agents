import sys
import json
import csv
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                lines.append(obj)
        return lines
    except Exception:
        return None


def _read_csv_with_header(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return rows, header
    except Exception:
        return None, None


def _safe_parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_bool(s: str) -> Optional[bool]:
    if isinstance(s, bool):
        return s
    if not isinstance(s, str):
        return None
    t = s.strip().lower()
    if t == "true":
        return True
    if t == "false":
        return False
    return None


def _parse_float(s: Any) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _parse_int(s: Any) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return None


def _parse_simple_yaml_weights(path: Path) -> Optional[Dict[str, float]]:
    txt = _read_text(path)
    if txt is None:
        return None
    weights: Dict[str, float] = {}
    in_weights = False
    try:
        for raw_line in txt.splitlines():
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            if not in_weights:
                if line.strip() == "weights:":
                    in_weights = True
                continue
            else:
                if not line.startswith(" "):
                    break
                stripped = line.strip()
                if ":" not in stripped:
                    return None
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                num = _parse_float(val)
                if num is None:
                    return None
                weights[key] = float(num)
        required = {"attendance", "recency", "ticketed_bonus", "community_quote_bonus"}
        if not required.issubset(set(weights.keys())):
            return None
        return weights
    except Exception:
        return None


def _compute_expected_metrics(workspace: Path) -> Optional[Dict[str, Any]]:
    bookstores_path = workspace / "input" / "bookstores.csv"
    events_path = workspace / "input" / "events.csv"
    ref_path = workspace / "config" / "reference_date.txt"

    bookstores_rows, _ = _read_csv_with_header(bookstores_path)
    events_rows, _ = _read_csv_with_header(events_path)
    ref_txt = _read_text(ref_path)

    if bookstores_rows is None or events_rows is None or ref_txt is None:
        return None

    ref_txt = ref_txt.strip()
    ref_date = _safe_parse_date(ref_txt)
    if ref_date is None:
        return None
    window_start = ref_date
    window_end = ref_date + timedelta(days=14)

    bookstores_count = len(bookstores_rows)
    events_total = len(events_rows)

    upcoming_count = 0
    for row in events_rows:
        d = _safe_parse_date(row.get("date", ""))
        if d is None:
            return None
        if window_start <= d <= window_end:
            upcoming_count += 1

    expected = {
        "bookstores_count": bookstores_count,
        "events_total": events_total,
        "upcoming_window_start": window_start.isoformat(),
        "upcoming_window_end": window_end.isoformat(),
        "upcoming_events_count": upcoming_count,
    }
    return expected


def _compute_expected_brief(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    bookstores_path = workspace / "input" / "bookstores.csv"
    events_path = workspace / "input" / "events.csv"
    interviews_path = workspace / "input" / "interviews.jsonl"
    weights_path = workspace / "config" / "ranking.yaml"
    ref_path = workspace / "config" / "reference_date.txt"

    bookstores_rows, _ = _read_csv_with_header(bookstores_path)
    events_rows, _ = _read_csv_with_header(events_path)
    interviews_rows = _read_jsonl(interviews_path)
    weights = _parse_simple_yaml_weights(weights_path)
    ref_txt = _read_text(ref_path)

    if any(x is None for x in [bookstores_rows, events_rows, interviews_rows, weights, ref_txt]):
        return None

    ref_date = _safe_parse_date(ref_txt.strip())
    if ref_date is None:
        return None
    window_start = ref_date
    window_end = ref_date + timedelta(days=14)

    bookstores_by_id: Dict[str, Dict[str, str]] = {}
    for b in bookstores_rows:  # type: ignore
        bid = b.get("id", "")
        if bid:
            bookstores_by_id[bid] = b

    top_quote_by_bookstore: Dict[str, str] = {}
    for obj in interviews_rows:  # type: ignore
        bsid = obj.get("bookstore_id")
        tags = obj.get("tags")
        quote = obj.get("quote")
        if not isinstance(bsid, str) or not isinstance(tags, list) or not isinstance(quote, str):
            continue
        if "community" in [str(t) for t in tags]:
            if bsid not in top_quote_by_bookstore:
                top_quote_by_bookstore[bsid] = quote

    scored_events = []
    for e in events_rows:  # type: ignore
        bsid = e.get("bookstore_id")
        d = _safe_parse_date(e.get("date", ""))
        if bsid is None or d is None:
            return None
        if not (window_start <= d <= window_end):
            continue
        attendance = _parse_int(e.get("attendance_estimate"))
        if attendance is None:
            return None
        ticketed_val = _parse_bool(e.get("ticketed"))
        if ticketed_val is None:
            return None

        days_until = (d - ref_date).days
        score = (
            attendance * weights["attendance"]
            + (14 - days_until) * weights["recency"]
            + (weights["ticketed_bonus"] if ticketed_val else 0.0)
            + (weights["community_quote_bonus"] if (top_quote_by_bookstore.get(bsid) is not None) else 0.0)
        )

        bs = bookstores_by_id.get(bsid)
        if bs is None:
            return None
        top_quote = top_quote_by_bookstore.get(bsid, "")

        scored_events.append({
            "event_date": d.isoformat(),
            "bookstore_id": bsid,
            "bookstore_name": bs.get("name", ""),
            "city": bs.get("city", ""),
            "event_title": e.get("title", ""),
            "category": e.get("category", ""),
            "attendance_estimate": attendance,
            "score": float(score),
            "top_quote": top_quote,
        })

    scored_events.sort(key=lambda r: (-r["score"], -r["attendance_estimate"], r["bookstore_name"]))

    top = scored_events[:5]
    brief_rows = []
    for i, r in enumerate(top, start=1):
        brief_rows.append({
            "rank": i,
            "event_date": r["event_date"],
            "bookstore_name": r["bookstore_name"],
            "city": r["city"],
            "event_title": r["event_title"],
            "category": r["category"],
            "attendance_estimate": r["attendance_estimate"],
            "score": r["score"],
            "top_quote": r["top_quote"],
        })
    return brief_rows


def _compare_metrics(output_metrics: Optional[Dict[str, Any]], expected_metrics: Optional[Dict[str, Any]]) -> bool:
    if output_metrics is None or expected_metrics is None:
        return False
    return output_metrics == expected_metrics


def _load_validation_json(path: Path) -> Optional[Dict[str, Any]]:
    return _read_json(path)


def _get_required_columns_truth(workspace: Path) -> Optional[Dict[str, bool]]:
    truth: Dict[str, bool] = {}

    bookstores_path = workspace / "input" / "bookstores.csv"
    events_path = workspace / "input" / "events.csv"
    interviews_path = workspace / "input" / "interviews.jsonl"

    rows_b, header_b = _read_csv_with_header(bookstores_path)
    required_bookstores = {"id", "name", "city", "neighborhood", "nonprofit"}
    truth["bookstores.csv"] = (header_b is not None and set(header_b) == required_bookstores and rows_b is not None)

    rows_e, header_e = _read_csv_with_header(events_path)
    required_events = {"bookstore_id", "date", "title", "category", "attendance_estimate", "ticketed"}
    truth["events.csv"] = (header_e is not None and set(header_e) == required_events and rows_e is not None)

    jsonl = _read_jsonl(interviews_path)
    ok_interviews = False
    if jsonl is not None and len(jsonl) > 0:
        ok_interviews = True
        for obj in jsonl:
            if not isinstance(obj, dict):
                ok_interviews = False
                break
            for k in ["bookstore_id", "person", "role", "quote", "tags"]:
                if k not in obj:
                    ok_interviews = False
                    break
            if not ok_interviews:
                break
    truth["interviews.jsonl"] = ok_interviews

    return truth


def _compute_foreign_key_truth(workspace: Path) -> Optional[bool]:
    bookstores_path = workspace / "input" / "bookstores.csv"
    events_path = workspace / "input" / "events.csv"
    b_rows, _ = _read_csv_with_header(bookstores_path)
    e_rows, _ = _read_csv_with_header(events_path)
    if b_rows is None or e_rows is None:
        return None
    b_ids = {b.get("id", "") for b in b_rows}
    for e in e_rows:
        if e.get("bookstore_id") not in b_ids:
            return False
    return True


def _compare_brief_csv_to_expected(workspace: Path, expected_rows: Optional[List[Dict[str, Any]]]) -> Tuple[float, float]:
    brief_path = workspace / "output" / "brief.csv"
    rows, header = _read_csv_with_header(brief_path)
    if rows is None or header is None or expected_rows is None:
        return 0.0, 0.0

    expected_header = ["rank", "event_date", "bookstore_name", "city", "event_title", "category", "attendance_estimate", "score", "top_quote"]
    columns_ok = header == expected_header

    if len(rows) != len(expected_rows):
        return (1.0 if columns_ok else 0.0), 0.0

    for i, row in enumerate(rows):
        exp = expected_rows[i]
        r_rank = _parse_int(row.get("rank"))
        if r_rank != exp["rank"]:
            return (1.0 if columns_ok else 0.0), 0.0
        if row.get("event_date") != exp["event_date"]:
            return (1.0 if columns_ok else 0.0), 0.0
        if row.get("bookstore_name") != exp["bookstore_name"]:
            return (1.0 if columns_ok else 0.0), 0.0
        if row.get("city") != exp["city"]:
            return (1.0 if columns_ok else 0.0), 0.0
        if row.get("event_title") != exp["event_title"]:
            return (1.0 if columns_ok else 0.0), 0.0
        if row.get("category") != exp["category"]:
            return (1.0 if columns_ok else 0.0), 0.0
        r_att = _parse_int(row.get("attendance_estimate"))
        if r_att != exp["attendance_estimate"]:
            return (1.0 if columns_ok else 0.0), 0.0
        r_score = _parse_float(row.get("score"))
        if r_score is None or abs(r_score - float(exp["score"])) > 1e-6:
            return (1.0 if columns_ok else 0.0), 0.0
        if (row.get("top_quote") or "") != (exp["top_quote"] or ""):
            return (1.0 if columns_ok else 0.0), 0.0

    return (1.0 if columns_ok else 0.0), 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "cron_schedule_correct": 0.0,
        "run_script_has_expected_paths": 0.0,
        "validation_json_present_and_fields": 0.0,
        "validation_checks_match_truth": 0.0,
        "validation_status_consistent": 0.0,
        "metrics_json_matches_expected": 0.0,
        "brief_csv_columns_correct": 0.0,
        "brief_csv_top5_correct": 0.0,
        "artifacts_dependency_check": 0.0,
        "log_last_run_present": 0.0,
    }

    cron_path = workspace / "scheduler" / "indie_bookstores.cron"
    cron_txt = _read_text(cron_path)
    if cron_txt is not None:
        lines = [ln for ln in (ln.strip() for ln in cron_txt.splitlines()) if ln != ""]
        required_line = "0 7 * * * /bin/bash ./scripts/run_pipeline.sh"
        if len(lines) == 1 and lines[0] == required_line:
            scores["cron_schedule_correct"] = 1.0

    run_script_path = workspace / "scripts" / "run_pipeline.sh"
    run_txt = _read_text(run_script_path)
    if run_txt is not None:
        needed = [
            "output/validation.json",
            "output/metrics.json",
            "output/brief.csv",
            "output/logs/last_run.txt",
        ]
        if all(x in run_txt for x in needed):
            scores["run_script_has_expected_paths"] = 1.0

    out_metrics_path = workspace / "output" / "metrics.json"
    out_metrics = _read_json(out_metrics_path)
    tests_metrics_path = workspace / "tests" / "expected_metrics.json"
    tests_metrics = _read_json(tests_metrics_path)

    if out_metrics is not None and tests_metrics is not None and out_metrics == tests_metrics:
        scores["metrics_json_matches_expected"] = 1.0

    validation_path = workspace / "output" / "validation.json"
    validation = _load_validation_json(validation_path)

    truth_required_cols = _get_required_columns_truth(workspace)
    truth_foreign_key = _compute_foreign_key_truth(workspace)
    truth_metrics_match = (out_metrics is not None and tests_metrics is not None and out_metrics == tests_metrics)

    def _extract_required_cols_from_validation(val: Dict[str, Any]) -> Optional[Dict[str, bool]]:
        details = val.get("details")
        if not isinstance(details, dict):
            return None
        rc = details.get("required_columns_present")
        if not isinstance(rc, dict):
            return None
        result: Dict[str, bool] = {}
        for key in ["bookstores.csv", "events.csv", "interviews.jsonl"]:
            candidates = [key, f"input/{key}"]
            found = None
            for c in candidates:
                if c in rc:
                    found = rc[c]
                    break
            if found is None:
                return None
            if isinstance(found, bool):
                result[key] = found
            else:
                return None
        return result

    if isinstance(validation, dict) and "status" in validation and "details" in validation and isinstance(validation["details"], dict):
        details = validation["details"]
        has_required = "required_columns_present" in details and "foreign_key_ok" in details and "metrics_match" in details
        if has_required:
            scores["validation_json_present_and_fields"] = 1.0

        v_required_cols = _extract_required_cols_from_validation(validation)
        v_fk = details.get("foreign_key_ok")
        v_metrics_match = details.get("metrics_match")

        rc_ok = (v_required_cols is not None and truth_required_cols is not None and all(v_required_cols.get(k) == truth_required_cols.get(k) for k in ["bookstores.csv", "events.csv", "interviews.jsonl"]))
        fk_ok = (isinstance(v_fk, bool) and truth_foreign_key is not None and v_fk == truth_foreign_key)
        mm_ok = (isinstance(v_metrics_match, bool) and v_metrics_match == truth_metrics_match)

        if rc_ok and fk_ok and mm_ok:
            scores["validation_checks_match_truth"] = 1.0

        status = validation.get("status")
        if isinstance(status, str):
            should_pass = (rc_ok and fk_ok and mm_ok)
            if (should_pass and status == "PASSED") or ((not should_pass) and status == "FAILED"):
                scores["validation_status_consistent"] = 1.0

    expected_brief = _compute_expected_brief(workspace)
    cols_score, rows_score = _compare_brief_csv_to_expected(workspace, expected_brief)
    scores["brief_csv_columns_correct"] = cols_score
    scores["brief_csv_top5_correct"] = rows_score

    brief_path = workspace / "output" / "brief.csv"
    if brief_path.exists():
        if (workspace / "output" / "validation.json").exists() and (workspace / "output" / "metrics.json").exists():
            scores["artifacts_dependency_check"] = 1.0
        else:
            scores["artifacts_dependency_check"] = 0.0
    else:
        scores["artifacts_dependency_check"] = 0.0

    log_path = workspace / "output" / "logs" / "last_run.txt"
    log_txt = _read_text(log_path)
    if log_txt is not None:
        lines = [ln for ln in (ln.rstrip("\n") for ln in log_txt.splitlines())]
        nonempty = [ln for ln in lines if ln != ""]
        if len(nonempty) == 1:
            scores["log_last_run_present"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()