import csv
import json
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _write_json(obj: Dict[str, Any]) -> None:
    print(json.dumps(obj))


def _parse_notes(notes_text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    m = re.search(r"EPA\s+limit:\s*([0-9]+(?:\.[0-9]+)?)\s*mg/L", notes_text, re.IGNORECASE)
    if m:
        try:
            out["epa_limit_mg_L"] = float(m.group(1))
        except Exception:
            out["epa_limit_mg_L"] = None
    else:
        out["epa_limit_mg_L"] = None
    m2 = re.search(r"Meeting:\s*(.+)", notes_text)
    out["meeting"] = m2.group(1).strip() if m2 else None
    m3 = re.search(r"When:\s*(.+)", notes_text)
    out["when"] = m3.group(1).strip() if m3 else None
    m4 = re.search(r"Where:\s*(.+)", notes_text)
    out["where"] = m4.group(1).strip() if m4 else None
    mt = re.search(r"Tone:\s*(.+)", notes_text)
    out["tone"] = mt.group(1).strip() if mt else None
    return out


def _parse_month_yyyy_mm(date_str: str) -> Tuple[int, int]:
    try:
        parts = date_str.strip().split("-")
        return int(parts[0]), int(parts[1])
    except Exception:
        return (0, 0)


_MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


def _month_label_from_yyyy_mm(date_str: str) -> Optional[str]:
    y, m = _parse_month_yyyy_mm(date_str)
    if y == 0 or m not in _MONTH_NAMES:
        return None
    return f"{_MONTH_NAMES[m]} {y}"


def _yyyy_mm_from_month_label(label: str) -> Optional[str]:
    try:
        parts = label.strip().split()
        if len(parts) != 2:
            return None
        month_name, year_str = parts
        rev = {v: k for k, v in _MONTH_NAMES.items()}
        if month_name not in rev:
            return None
        m = rev[month_name]
        y = int(year_str)
        return f"{y:04d}-{m:02d}"
    except Exception:
        return None


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        if m:
            try:
                return float(m.group(0))
            except Exception:
                return None
        return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        m = re.search(r"[-+]?\d+", s)
        if m:
            try:
                return int(m.group(0))
            except Exception:
                return None
        return None


def _compute_last12_expected(rows: List[Dict[str, str]]) -> Optional[List[Dict[str, Any]]]:
    required_cols = ["date", "avg_nitrate_mg_L", "samples"]
    for c in required_cols:
        if not rows or c not in rows[0]:
            return None
    try:
        sorted_rows = sorted(rows, key=lambda r: (_parse_month_yyyy_mm(r["date"])[0], _parse_month_yyyy_mm(r["date"])[1]))
    except Exception:
        return None
    last12 = sorted_rows[-12:] if len(sorted_rows) >= 12 else sorted_rows[:]
    out: List[Dict[str, Any]] = []
    for r in last12:
        f = _safe_float(r["avg_nitrate_mg_L"])
        i = _safe_int(r["samples"])
        if f is None or i is None:
            return None
        out.append({"date": r["date"], "avg_nitrate_mg_L": f, "samples": i})
    return out


def _compute_metrics_from_last12(last12: List[Dict[str, Any]], epa_limit: float) -> Optional[Dict[str, Any]]:
    if not last12 or epa_limit is None:
        return None
    try:
        avgs = [r["avg_nitrate_mg_L"] for r in last12]
        samples = [r["samples"] for r in last12]
        dates = [r["date"] for r in last12]
        last12_avg = round(mean(avgs), 1)
        max_val = max(avgs)
        max_idx = avgs.index(max_val)
        max_month_label = _month_label_from_yyyy_mm(dates[max_idx])
        if max_month_label is None:
            return None
        exceed_count = sum(1 for v in avgs if v >= epa_limit)
        total_samples = sum(samples)
        return {
            "last12_avg_mg_L": last12_avg,
            "last12_max_mg_L": round(max_val, 1),
            "last12_max_month": max_month_label,
            "last12_count_exceeding_limit": int(exceed_count),
            "last12_total_samples": int(total_samples),
        }
    except Exception:
        return None


def _find_ask_paragraph(text: str) -> Optional[str]:
    lines = text.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("ask"):
            idx = i
            break
    if idx is None:
        return None
    first_line = lines[idx]
    after_colon = ""
    if ":" in first_line:
        after_colon = first_line.split(":", 1)[1].strip()
    i = idx + 1
    para_lines: List[str] = []
    if after_colon:
        para_lines.append(after_colon)
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            break
        para_lines.append(line)
        i += 1
    para = " ".join(l.strip() for l in para_lines).strip()
    return para


def _contains_number_with_unit(text: str, value: float, unit: str = "mg/L") -> bool:
    pattern = re.compile(rf"\b{re.escape(str(value))}\s*{re.escape(unit)}\b")
    return bool(pattern.search(text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "last12_records_file_exists": 0.0,
        "last12_records_columns_and_order": 0.0,
        "last12_records_row_subset_and_order": 0.0,
        "last12_metrics_file_exists": 0.0,
        "last12_metrics_schema_valid": 0.0,
        "last12_metrics_values_correct": 0.0,
        "letter_updated_exists": 0.0,
        "letter_placeholders_replaced": 0.0,
        "letter_contains_correct_numbers_and_units": 0.0,
        "letter_includes_meeting_details": 0.0,
        "letter_epa_spelled_out": 0.0,
        "letter_ask_paragraph_covers_three_points": 0.0,
        "letter_max_month_value_consistency": 0.0,
        "status_update_exists": 0.0,
        "status_update_length_120_180_words": 0.0,
        "status_update_includes_meeting_invite": 0.0,
        "status_update_max_and_limit_consistency": 0.0,
        "crossfile_consistency_max_in_records": 0.0,
    }

    # Load inputs
    input_csv = workspace / "input" / "iowa_river_nitrate_monthly.csv"
    input_notes = workspace / "input" / "notes.txt"
    input_letter = workspace / "input" / "community_draft_letter.md"

    headers_in, rows_in = _load_csv_dicts(input_csv)
    notes_text = _read_text(input_notes)
    draft_letter_text = _read_text(input_letter)  # not used for grading outputs directly, but kept if needed

    # Parse notes for threshold and meeting details
    epa_limit = None
    meeting_when = None
    meeting_where = None
    if notes_text is not None:
        notes = _parse_notes(notes_text)
        epa_limit = notes.get("epa_limit_mg_L")
        meeting_when = notes.get("when")
        meeting_where = notes.get("where")

    # Compute expected last12 and metrics
    expected_last12: Optional[List[Dict[str, Any]]] = None
    expected_metrics: Optional[Dict[str, Any]] = None
    if headers_in is not None and rows_in is not None and epa_limit is not None:
        expected_last12 = _compute_last12_expected(rows_in)
        if expected_last12 is not None:
            expected_metrics = _compute_metrics_from_last12(expected_last12, epa_limit)

    # Check outputs/last12_records.csv
    out_last12_path = workspace / "outputs" / "last12_records.csv"
    headers_last12, rows_last12 = _load_csv_dicts(out_last12_path)
    if headers_last12 is not None and rows_last12 is not None:
        scores["last12_records_file_exists"] = 1.0
        if headers_in is not None and headers_last12 == headers_in:
            scores["last12_records_columns_and_order"] = 1.0
        if expected_last12 is not None:
            try:
                if len(rows_last12) == len(expected_last12):
                    ok_rows = True
                    for i, r in enumerate(rows_last12):
                        exp = expected_last12[i]
                        if r.get("date", "").strip() != exp["date"]:
                            ok_rows = False
                            break
                        f = _safe_float(r.get("avg_nitrate_mg_L", ""))
                        i_samples = _safe_int(r.get("samples", ""))
                        if f is None or i_samples is None:
                            ok_rows = False
                            break
                        if abs(f - exp["avg_nitrate_mg_L"]) > 1e-9 or i_samples != exp["samples"]:
                            ok_rows = False
                            break
                    if ok_rows:
                        scores["last12_records_row_subset_and_order"] = 1.0
            except Exception:
                pass

    # Check outputs/last12_metrics.csv
    out_metrics_path = workspace / "outputs" / "last12_metrics.csv"
    headers_metrics, rows_metrics = _load_csv_dicts(out_metrics_path)
    if headers_metrics is not None and rows_metrics is not None:
        scores["last12_metrics_file_exists"] = 1.0
        if headers_metrics == ["metric", "value"]:
            scores["last12_metrics_schema_valid"] = 1.0
        if expected_metrics is not None:
            try:
                metrics_map: Dict[str, str] = {r.get("metric", ""): r.get("value", "") for r in rows_metrics}
                required_keys = [
                    "last12_avg_mg_L",
                    "last12_max_mg_L",
                    "last12_max_month",
                    "last12_count_exceeding_limit",
                    "last12_total_samples",
                ]
                all_present = all(k in metrics_map for k in required_keys)
                if all_present:
                    ok = True
                    v_avg = _safe_float(metrics_map["last12_avg_mg_L"])
                    if v_avg is None or abs(v_avg - expected_metrics["last12_avg_mg_L"]) > 1e-9:
                        ok = False
                    v_max = _safe_float(metrics_map["last12_max_mg_L"])
                    if v_max is None or abs(v_max - expected_metrics["last12_max_mg_L"]) > 1e-9:
                        ok = False
                    v_mo = metrics_map["last12_max_month"].strip()
                    if v_mo != expected_metrics["last12_max_month"]:
                        ok = False
                    v_exc = _safe_int(metrics_map["last12_count_exceeding_limit"])
                    if v_exc is None or v_exc != expected_metrics["last12_count_exceeding_limit"]:
                        ok = False
                    v_tot = _safe_int(metrics_map["last12_total_samples"])
                    if v_tot is None or v_tot != expected_metrics["last12_total_samples"]:
                        ok = False
                    if ok:
                        scores["last12_metrics_values_correct"] = 1.0
            except Exception:
                pass

    # Check outputs/community_letter_updated.md
    out_letter_path = workspace / "outputs" / "community_letter_updated.md"
    letter_text = _read_text(out_letter_path)
    if letter_text is not None:
        scores["letter_updated_exists"] = 1.0
        placeholders = [
            "{{LAST_12M_AVG}}",
            "{{EPA_LIMIT}}",
            "{{NUM_EXCEED}}",
            "{{MAX_MONTH_LABEL}}",
            "{{MAX_VALUE}}",
            "{{MEETING_WHEN}}",
            "{{MEETING_WHERE}}",
        ]
        if all(ph not in letter_text for ph in placeholders):
            scores["letter_placeholders_replaced"] = 1.0
        ok_nums = False
        if expected_metrics is not None and epa_limit is not None:
            avg_ok = _contains_number_with_unit(letter_text, expected_metrics["last12_avg_mg_L"], "mg/L")
            max_ok = _contains_number_with_unit(letter_text, expected_metrics["last12_max_mg_L"], "mg/L")
            limit_ok = _contains_number_with_unit(letter_text, float(epa_limit), "mg/L")
            month_ok = expected_metrics["last12_max_month"] in letter_text
            exc_present = str(expected_metrics["last12_count_exceeding_limit"]) in letter_text
            ok_nums = avg_ok and max_ok and limit_ok and month_ok and exc_present
        if ok_nums:
            scores["letter_contains_correct_numbers_and_units"] = 1.0
        if (meeting_when and meeting_where) and (meeting_when in letter_text and meeting_where in letter_text):
            scores["letter_includes_meeting_details"] = 1.0
        if "U.S. Environmental Protection Agency (EPA)" in letter_text:
            scores["letter_epa_spelled_out"] = 1.0
        ask_para = _find_ask_paragraph(letter_text)
        if ask_para is not None:
            para = ask_para.strip().lower()
            if para:
                pt1 = ("funding" in para) and (("sampling" in para) or ("stream" in para))
                pt2 = ("monthly" in para) and (("summary" in para) or ("report" in para) or ("update" in para)) and (("website" in para) or ("site" in para))
                pt3 = ("volunteer" in para) and (("monitor" in para) or ("monitoring" in para)) and (("partner" in para) or ("partnership" in para) or ("partnerships" in para))
                no_placeholder = ("[" not in ask_para and "]" not in ask_para and "{{" not in ask_para and "}}" not in ask_para)
                if pt1 and pt2 and pt3 and no_placeholder:
                    scores["letter_ask_paragraph_covers_three_points"] = 1.0
        if expected_metrics is not None:
            mo_ok = expected_metrics["last12_max_month"] in letter_text
            mx_ok = _contains_number_with_unit(letter_text, expected_metrics["last12_max_mg_L"], "mg/L")
            if mo_ok and mx_ok:
                scores["letter_max_month_value_consistency"] = 1.0

    # Status update checks
    out_status_path = workspace / "outputs" / "status_update.txt"
    status_text = _read_text(out_status_path)
    if status_text is not None:
        scores["status_update_exists"] = 1.0
        words = re.findall(r"\b\w+\b", status_text)
        if 120 <= len(words) <= 180:
            scores["status_update_length_120_180_words"] = 1.0
        if (meeting_when and meeting_where) and (meeting_when in status_text and meeting_where in status_text):
            scores["status_update_includes_meeting_invite"] = 1.0
        ok_stat = False
        if expected_metrics is not None:
            max_month_present = expected_metrics["last12_max_month"] in status_text
            max_val_present = _contains_number_with_unit(status_text, expected_metrics["last12_max_mg_L"], "mg/L")
            limit_pattern_ok = (epa_limit is not None and _contains_number_with_unit(status_text, float(epa_limit), "mg/L"))
            if max_month_present and max_val_present and limit_pattern_ok:
                ok_stat = True
        if ok_stat:
            scores["status_update_max_and_limit_consistency"] = 1.0

    # Cross-file consistency: max month must appear in last12_records.csv and correspond to the same row/value
    if expected_metrics is not None and rows_last12 is not None:
        label = expected_metrics["last12_max_month"]
        yyyy_mm = _yyyy_mm_from_month_label(label) if label else None
        if yyyy_mm:
            found_row = None
            for r in rows_last12:
                if r.get("date", "").strip() == yyyy_mm:
                    found_row = r
                    break
            if found_row is not None:
                fv = _safe_float(found_row.get("avg_nitrate_mg_L", ""))
                if fv is not None and abs(fv - expected_metrics["last12_max_mg_L"]) <= 1e-9:
                    scores["crossfile_consistency_max_in_records"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    _write_json(result)


if __name__ == "__main__":
    main()