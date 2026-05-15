import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional


REQUIRED_INPUT_SCHEMA = [
    "incident_id",
    "incident_type",
    "region",
    "report_time",
    "response_time_minutes",
    "status",
    "households_assessed",
    "displaced_persons",
]

SUMMARY_COLUMNS = [
    "incident_type",
    "total_incidents",
    "closed_incidents",
    "open_incidents",
    "mean_response_time_minutes",
    "median_response_time_minutes",
    "total_households_assessed",
    "total_displaced_persons",
]

PROCESSED_FILES_COLUMNS = [
    "file_path",
    "row_count",
    "min_report_time",
    "max_report_time",
]


def _parse_iso8601_z(dt_str: str) -> Optional[datetime]:
    try:
        s = dt_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _to_zulu(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = [dict(row) for row in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _list_assessment_files(workspace: Path) -> List[Path]:
    input_dir = workspace / "input"
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    return sorted([p for p in input_dir.glob("assessments_*.csv") if p.is_file()])


def _validate_input_rows(rows: List[Dict[str, str]]) -> bool:
    for r in rows:
        for k in REQUIRED_INPUT_SCHEMA:
            if k not in r:
                return False
        if _parse_iso8601_z(r.get("report_time", "")) is None:
            return False
        try:
            int(r.get("response_time_minutes", ""))
            int(r.get("households_assessed", ""))
            int(r.get("displaced_persons", ""))
        except Exception:
            return False
        status = str(r.get("status", "")).strip().lower()
        if status not in {"open", "closed"}:
            return False
    return True


def _compute_file_stats(rows: List[Dict[str, str]]) -> Tuple[int, Optional[datetime], Optional[datetime]]:
    times = []
    for r in rows:
        dt = _parse_iso8601_z(r["report_time"])
        if dt is None:
            return 0, None, None
        times.append(dt)
    if not times:
        return 0, None, None
    return len(rows), min(times), max(times)


def _median(values: List[float]) -> float:
    n = len(values)
    if n == 0:
        return float("nan")
    values_sorted = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        return float(values_sorted[mid])
    return (values_sorted[mid - 1] + values_sorted[mid]) / 2.0


def _compute_summary(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, float]]:
    groups: Dict[str, List[Dict[str, str]]] = {}
    for r in rows:
        itype = r["incident_type"]
        groups.setdefault(itype, []).append(r)

    def stats_for(group_rows: List[Dict[str, str]]) -> Dict[str, float]:
        total = len(group_rows)
        closed = sum(1 for r in group_rows if str(r["status"]).strip().lower() == "closed")
        open_cnt = sum(1 for r in group_rows if str(r["status"]).strip().lower() == "open")
        resp = [int(r["response_time_minutes"]) for r in group_rows]
        mean_resp = sum(resp) / len(resp) if resp else 0.0
        median_resp = _median(resp) if resp else 0.0
        hh = sum(int(r["households_assessed"]) for r in group_rows)
        disp = sum(int(r["displaced_persons"]) for r in group_rows)
        return {
            "total_incidents": float(total),
            "closed_incidents": float(closed),
            "open_incidents": float(open_cnt),
            "mean_response_time_minutes": float(mean_resp),
            "median_response_time_minutes": float(median_resp),
            "total_households_assessed": float(hh),
            "total_displaced_persons": float(disp),
        }

    summary: Dict[str, Dict[str, float]] = {}
    for itype, group in groups.items():
        summary[itype] = stats_for(group)

    summary["ALL"] = stats_for(rows)
    return summary


def _almost_equal(a: float, b: float, tol: float = 0.01) -> bool:
    if a == b:
        return True
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def _extract_numbers(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r'(?<![%\d])(-?\d+(?:\.\d+)?)(?![%\d])', text):
        try:
            nums.append(float(m.group(1)))
        except Exception:
            continue
    return nums


def _extract_percentages(text: str) -> List[float]:
    vals = []
    for m in re.finditer(r'(-?\d+(?:\.\d+)?)\s*%', text):
        try:
            vals.append(float(m.group(1)))
        except Exception:
            continue
    return vals


def _text_has_number_approx(text: str, expected: float, tol: float = 0.5) -> bool:
    for num in _extract_numbers(text):
        if _almost_equal(num, expected, tol):
            return True
    return False


def _text_has_percentage_for_ratio(text: str, ratio: float, tol_percent: float = 0.5) -> bool:
    expected_pct = ratio * 100.0
    for pct in _extract_percentages(text):
        if _almost_equal(pct, expected_pct, tol_percent):
            return True
    return False


def _normalize_rel_path(workspace: Path, p: Path) -> str:
    try:
        rel = p.relative_to(workspace)
        return str(rel).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def _parse_summary_csv(path: Path) -> Tuple[Optional[Dict[str, Dict[str, float]]], Optional[List[str]]]:
    rows, headers = _safe_read_csv_dicts(path)
    if rows is None or headers is None:
        return None, None
    if set(headers) != set(SUMMARY_COLUMNS):
        return None, None
    data: Dict[str, Dict[str, float]] = {}
    for r in rows:
        if "incident_type" not in r:
            return None, None
        itype = r["incident_type"]
        try:
            vals = {
                "total_incidents": float(r["total_incidents"]),
                "closed_incidents": float(r["closed_incidents"]),
                "open_incidents": float(r["open_incidents"]),
                "mean_response_time_minutes": float(r["mean_response_time_minutes"]),
                "median_response_time_minutes": float(r["median_response_time_minutes"]),
                "total_households_assessed": float(r["total_households_assessed"]),
                "total_displaced_persons": float(r["total_displaced_persons"]),
            }
        except Exception:
            return None, None
        data[itype] = vals
    return data, headers


def _parse_processed_files_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    rows, headers = _safe_read_csv_dicts(path)
    if rows is None or headers is None:
        return None
    if set(headers) != set(PROCESSED_FILES_COLUMNS):
        return None
    for r in rows:
        for k in PROCESSED_FILES_COLUMNS:
            if k not in r:
                return None
    return rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "processed_files_structure": 0.0,
        "processed_files_values": 0.0,
        "summary_by_type_structure": 0.0,
        "summary_by_type_values": 0.0,
        "sitrep_coverage_window_includes_min_max": 0.0,
        "sitrep_overall_totals_present": 0.0,
        "sitrep_closure_rate_present": 0.0,
        "sitrep_mean_response_time_present": 0.0,
        "sitrep_top3_from_summary_present": 0.0,
        "sitrep_methodology_files_and_counts": 0.0,
        "sitrep_references_summary_csv": 0.0,
        "email_has_to_and_subject_and_length": 0.0,
        "email_includes_metrics": 0.0,
        "email_names_top3_from_summary": 0.0,
        "email_references_attachments": 0.0,
    }

    input_files = _list_assessment_files(workspace)
    all_rows: List[Dict[str, str]] = []
    input_file_stats: Dict[str, Dict[str, object]] = {}
    parsed_ok = True

    for f in input_files:
        rows, headers = _safe_read_csv_dicts(f)
        if rows is None or headers is None or not _validate_input_rows(rows):
            parsed_ok = False
            break
        count, min_dt, max_dt = _compute_file_stats(rows)
        if min_dt is None or max_dt is None:
            parsed_ok = False
            break
        all_rows.extend(rows)
        input_file_stats[f.name] = {
            "row_count": count,
            "min_dt": min_dt,
            "max_dt": max_dt,
            "min_str": _to_zulu(min_dt),
            "max_str": _to_zulu(max_dt),
            "path": f,
        }

    expected_summary: Optional[Dict[str, Dict[str, float]]] = None
    min_time_all: Optional[datetime] = None
    max_time_all: Optional[datetime] = None
    if parsed_ok and all_rows:
        expected_summary = _compute_summary(all_rows)
        min_time_all = min(_parse_iso8601_z(r["report_time"]) for r in all_rows)  # type: ignore
        max_time_all = max(_parse_iso8601_z(r["report_time"]) for r in all_rows)  # type: ignore

    outputs_dir = workspace / "outputs"
    summary_csv_path = outputs_dir / "summary_by_type.csv"
    processed_csv_path = outputs_dir / "processed_files.csv"
    sitrep_md_path = outputs_dir / "sitrep.md"
    email_txt_path = outputs_dir / "email_logistics.txt"

    processed_rows = _parse_processed_files_csv(processed_csv_path) if processed_csv_path.exists() else None
    if processed_rows is not None:
        if len(processed_rows) == len(input_files) and len(processed_rows) > 0:
            scores["processed_files_structure"] = 1.0
        else:
            if len(input_files) == 0 and len(processed_rows) == 0:
                scores["processed_files_structure"] = 1.0
        if parsed_ok and input_files:
            ok_vals = True
            seen_names = set()
            for r in processed_rows:
                fp = r["file_path"].replace("\\", "/").strip()
                fname = Path(fp).name
                seen_names.add(fname)
                if fname not in input_file_stats:
                    ok_vals = False
                    break
                exp = input_file_stats[fname]
                try:
                    rc = int(r["row_count"])
                except Exception:
                    ok_vals = False
                    break
                min_rep = r["min_report_time"].strip()
                max_rep = r["max_report_time"].strip()
                if rc != exp["row_count"]:
                    ok_vals = False
                    break
                parsed_min = _parse_iso8601_z(min_rep)
                parsed_max = _parse_iso8601_z(max_rep)
                if parsed_min is None or parsed_max is None:
                    ok_vals = False
                    break
                if parsed_min != exp["min_dt"] or parsed_max != exp["max_dt"]:
                    ok_vals = False
                    break
            if set(seen_names) != set(input_file_stats.keys()):
                ok_vals = False
            if ok_vals:
                scores["processed_files_values"] = 1.0
        elif len(input_files) == 0:
            if processed_rows == []:
                scores["processed_files_values"] = 1.0

    summary_parsed, summary_headers = (None, None)
    if summary_csv_path.exists():
        summary_parsed, summary_headers = _parse_summary_csv(summary_csv_path)
    if summary_parsed is not None:
        has_all = "ALL" in summary_parsed
        if parsed_ok and expected_summary is not None:
            expected_types = set(expected_summary.keys())
            got_types = set(summary_parsed.keys())
            if has_all and expected_types == got_types:
                scores["summary_by_type_structure"] = 1.0
        else:
            if has_all:
                scores["summary_by_type_structure"] = 1.0

        if parsed_ok and expected_summary is not None:
            ok_vals = True
            for itype, exp_vals in expected_summary.items():
                if itype not in summary_parsed:
                    ok_vals = False
                    break
                got_vals = summary_parsed[itype]
                for k in ["total_incidents", "closed_incidents", "open_incidents",
                          "total_households_assessed", "total_displaced_persons"]:
                    if int(exp_vals[k]) != int(got_vals[k]):
                        ok_vals = False
                        break
                if not ok_vals:
                    break
                for k in ["mean_response_time_minutes", "median_response_time_minutes"]:
                    if not _almost_equal(float(exp_vals[k]), float(got_vals[k]), tol=0.01):
                        ok_vals = False
                        break
                if not ok_vals:
                    break
            if ok_vals:
                scores["summary_by_type_values"] = 1.0

    sitrep_text = _safe_read_text(sitrep_md_path) if sitrep_md_path.exists() else None
    summary_for_top3 = summary_parsed
    if sitrep_text:
        if parsed_ok and min_time_all is not None and max_time_all is not None:
            min_str = _to_zulu(min_time_all)
            max_str = _to_zulu(max_time_all)
            if (min_str in sitrep_text) and (max_str in sitrep_text):
                scores["sitrep_coverage_window_includes_min_max"] = 1.0

        if parsed_ok and expected_summary is not None and "ALL" in expected_summary:
            all_row = expected_summary["ALL"]
            totals_present = True
            tot_inc = int(all_row["total_incidents"])
            tot_hh = int(all_row["total_households_assessed"])
            tot_disp = int(all_row["total_displaced_persons"])
            if str(tot_inc) not in sitrep_text:
                totals_present = False
            if str(tot_hh) not in sitrep_text:
                totals_present = False
            if str(tot_disp) not in sitrep_text:
                totals_present = False
            if totals_present:
                scores["sitrep_overall_totals_present"] = 1.0

            if all_row["total_incidents"] > 0:
                closure_ratio = float(all_row["closed_incidents"]) / float(all_row["total_incidents"])
                closure_ok = _text_has_percentage_for_ratio(sitrep_text, closure_ratio, tol_percent=0.5) or _text_has_number_approx(sitrep_text, closure_ratio, tol=0.01)
                if closure_ok:
                    scores["sitrep_closure_rate_present"] = 1.0

            mean_resp_all = float(expected_summary["ALL"]["mean_response_time_minutes"])
            if _text_has_number_approx(sitrep_text, mean_resp_all, tol=0.5):
                scores["sitrep_mean_response_time_present"] = 1.0

        if summary_for_top3 is not None:
            types_without_all = [(t, v) for t, v in summary_for_top3.items() if t != "ALL"]
            types_sorted = sorted(types_without_all, key=lambda tv: (-int(tv[1]["total_incidents"]), tv[0]))
            top3 = types_sorted[:3]
            ok_top3 = True
            for t, v in top3:
                count = int(v["total_incidents"])
                if (t not in sitrep_text) or (str(count) not in sitrep_text):
                    ok_top3 = False
                    break
            if ok_top3 and top3:
                scores["sitrep_top3_from_summary_present"] = 1.0

        processed_rows_for_method = processed_rows
        if processed_rows_for_method is not None:
            ok_method = True
            for r in processed_rows_for_method:
                fp = r["file_path"].replace("\\", "/")
                fname = Path(fp).name
                rc = r["row_count"].strip()
                if not ((fp in sitrep_text) or (fname in sitrep_text)):
                    ok_method = False
                    break
                if rc not in sitrep_text:
                    ok_method = False
                    break
            if ok_method and len(processed_rows_for_method) > 0:
                scores["sitrep_methodology_files_and_counts"] = 1.0

        if "outputs/summary_by_type.csv" in sitrep_text:
            scores["sitrep_references_summary_csv"] = 1.0

    email_text = _safe_read_text(email_txt_path) if email_txt_path.exists() else None
    if email_text:
        has_to = "logistics@org.example" in email_text
        subj_line_match = re.search(r'(?im)^\s*subject\s*:\s*(\S.+)$', email_text)
        subject_ok = subj_line_match is not None and subj_line_match.group(1).strip() != ""
        body_text = email_text
        if subj_line_match:
            _, end = subj_line_match.span(0)
            after = email_text[end:]
            body_text = after
        words = re.findall(r'\b\w+\b', body_text)
        length_ok = len(words) <= 150
        if has_to and subject_ok and length_ok:
            scores["email_has_to_and_subject_and_length"] = 1.0

        metrics_ok = False
        names_ok = False
        attachments_ok = False

        if parsed_ok and expected_summary is not None and "ALL" in expected_summary:
            all_row = expected_summary["ALL"]
            tot_inc = int(all_row["total_incidents"])
            mean_resp = float(all_row["mean_response_time_minutes"])
            if all_row["total_incidents"] > 0:
                closure_ratio = float(all_row["closed_incidents"]) / float(all_row["total_incidents"])
            else:
                closure_ratio = 0.0
            has_incidents = str(tot_inc) in email_text
            has_mean_resp = _text_has_number_approx(email_text, mean_resp, tol=0.5)
            has_closure = _text_has_percentage_for_ratio(email_text, closure_ratio, tol_percent=0.5) or _text_has_number_approx(email_text, closure_ratio, tol=0.01)
            if has_incidents and has_mean_resp and has_closure:
                metrics_ok = True

        if summary_for_top3 is not None:
            types_without_all = [(t, v) for t, v in summary_for_top3.items() if t != "ALL"]
            types_sorted = sorted(types_without_all, key=lambda tv: (-int(tv[1]["total_incidents"]), tv[0]))
            top3 = [t for t, _ in types_sorted[:3]]
            names_ok = all((t in email_text) for t in top3) and len(top3) > 0

        if ("outputs/sitrep.md" in email_text) and ("outputs/summary_by_type.csv" in email_text):
            attachments_ok = True

        if metrics_ok:
            scores["email_includes_metrics"] = 1.0
        if names_ok:
            scores["email_names_top3_from_summary"] = 1.0
        if attachments_ok:
            scores["email_references_attachments"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()