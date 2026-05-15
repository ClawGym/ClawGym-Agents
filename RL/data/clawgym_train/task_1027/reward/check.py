import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple


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


def _safe_parse_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _monday_of_week(date_str: str) -> str:
    dt = datetime.fromisoformat(date_str).date()
    monday = dt - timedelta(days=dt.weekday())
    return monday.isoformat()


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _compute_expected_summary(records: List[Dict[str, Any]], include_herbs: List[str]) -> List[Dict[str, Any]]:
    include_set = set(h.strip().lower() for h in include_herbs) if include_herbs else None
    aggregates: Dict[Tuple[str, str, str], float] = {}
    for r in records:
        date = r.get("date")
        borrower = r.get("borrower")
        herb = r.get("herb")
        grams_val = r.get("grams")
        if date is None or borrower is None or herb is None or grams_val is None:
            continue
        herb_norm = str(herb).strip()
        if include_set is not None and herb_norm.lower() not in include_set:
            continue
        grams = grams_val if isinstance(grams_val, (int, float)) else _to_float(grams_val)
        if grams is None:
            continue
        week_start = _monday_of_week(str(date).strip())
        key = (week_start, str(borrower).strip(), herb_norm)
        aggregates[key] = aggregates.get(key, 0.0) + float(grams)
    rows = [
        {"week_start": k[0], "borrower": k[1], "herb": k[2], "total_grams": v}
        for k, v in aggregates.items()
    ]
    rows.sort(key=lambda x: (x["week_start"], x["borrower"], x["herb"]))
    return rows


def _canonicalize_rows(rows: List[Dict[str, Any]]) -> Dict[Tuple[str, str, str], float]:
    result: Dict[Tuple[str, str, str], float] = {}
    for r in rows:
        try:
            ws = str(r["week_start"]).strip()
            bor = str(r["borrower"]).strip()
            herb = str(r["herb"]).strip()
            grams = r["total_grams"]
            grams_f = grams if isinstance(grams, (int, float)) else _to_float(grams)
            if grams_f is None:
                return {}
            key = (ws, bor, herb)
            result[key] = result.get(key, 0.0) + float(grams_f)
        except Exception:
            return {}
    return result


def _rows_equal(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]], tol: float = 1e-6) -> bool:
    exp_map = _canonicalize_rows(expected)
    act_map = _canonicalize_rows(actual)
    if expected and not exp_map:
        return False
    if set(exp_map.keys()) != set(act_map.keys()):
        return False
    for k in exp_map:
        if abs(exp_map[k] - act_map[k]) > tol:
            return False
    return True


def _load_workspace_records_and_config(workspace: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[str]]]:
    cfg_path = workspace / "config" / "herbshare.json"
    csv_path = workspace / "data" / "herb_borrows.csv"
    cfg = _safe_load_json(cfg_path)
    csv_rows = _safe_parse_csv_dicts(csv_path)
    if cfg is None or csv_rows is None:
        return None, None
    include_herbs = cfg.get("include_herbs", []) if isinstance(cfg, dict) else []
    records: List[Dict[str, Any]] = []
    for row in csv_rows:
        try:
            rec = {
                "date": row["date"].strip(),
                "borrower": row["borrower"].strip(),
                "herb": row["herb"].strip(),
                "grams": float(row["grams"]),
            }
            records.append(rec)
        except Exception:
            return None, None
    return records, include_herbs


def _validate_csv_output(path: Path, expected_rows: List[Dict[str, Any]]) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            expected_fields = ["week_start", "borrower", "herb", "total_grams"]
            if reader.fieldnames != expected_fields:
                return False
            actual_rows: List[Dict[str, Any]] = []
            for row in reader:
                for k in expected_fields:
                    if k not in row:
                        return False
                grams_f = _to_float(row["total_grams"])
                if grams_f is None:
                    return False
                actual_rows.append({
                    "week_start": row["week_start"].strip(),
                    "borrower": row["borrower"].strip(),
                    "herb": row["herb"].strip(),
                    "total_grams": grams_f,
                })
            return _rows_equal(expected_rows, actual_rows)
    except Exception:
        return False


def _validate_json_output(path: Path, expected_rows: List[Dict[str, Any]]) -> bool:
    if not path.exists():
        return False
    data = _safe_load_json(path)
    if not isinstance(data, list):
        return False
    actual_rows: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            return False
        for key in ["week_start", "borrower", "herb", "total_grams"]:
            if key not in item:
                return False
        grams = item["total_grams"]
        if not isinstance(grams, (int, float)):
            return False
        actual_rows.append({
            "week_start": str(item["week_start"]).strip(),
            "borrower": str(item["borrower"]).strip(),
            "herb": str(item["herb"]).strip(),
            "total_grams": float(grams),
        })
    return _rows_equal(expected_rows, actual_rows)


def _import_student_module(workspace: Path):
    try:
        src_path = workspace / "src" / "herbshare.py"
        if not src_path.exists():
            return None
        if str(workspace / "src") not in sys.path:
            sys.path.insert(0, str(workspace / "src"))
        import importlib
        return importlib.import_module("herbshare")
    except Exception:
        return None


def _list_all_expected_files(workspace: Path) -> List[Path]:
    expected_dirs = ["src", "data", "config", "input"]
    files: List[Path] = []
    for d in expected_dirs:
        dir_path = workspace / d
        if dir_path.exists() and dir_path.is_dir():
            for p in dir_path.rglob("*"):
                if p.is_file():
                    files.append(p)
    return files


def _parse_dir_overview_for_sizes(doc_text: str, expected_files: List[Path], workspace: Path) -> bool:
    if doc_text is None:
        return False
    lines = doc_text.splitlines()
    all_ok = True
    for p in expected_files:
        rel = p.relative_to(workspace).as_posix()
        size = p.stat().st_size
        matched_line = None
        for line in lines:
            if rel in line:
                matched_line = line
                break
        if matched_line is None:
            all_ok = False
            continue
        nums = re.findall(r"\d+", matched_line)
        if not nums:
            all_ok = False
            continue
        try:
            reported_size = int(nums[-1])
        except Exception:
            all_ok = False
            continue
        if reported_size != size:
            all_ok = False
    return all_ok


def _check_meeting_notes_decisions(text: str) -> bool:
    if text is None:
        return False
    t = text.lower()
    if "decisions" not in t:
        return False
    herbs_ok = all(h in t for h in ["basil", "rosemary", "thyme"])
    week_ok = ("monday" in t and "week" in t)
    formats_ok = ("csv" in t and "json" in t)
    units_ok = "grams" in t
    return herbs_ok and week_ok and formats_ok and units_ok


def _check_meeting_notes_action_items(text: str) -> bool:
    if text is None:
        return False
    t = text.lower()
    if "action items" not in t:
        return False
    has_alex = "alex" in t
    has_jamie = "jamie" in t
    has_pat = "pat" in t
    if not (has_alex and has_jamie and has_pat):
        return False
    alex_ok = ("alex" in t and (("implement" in t and "weekly" in t and "summary" in t) or ("csv" in t and "json" in t)))
    jamie_ok = ("jamie" in t and "email" in t and ("meeting notes" in t or "notes" in t))
    pat_ok = ("pat" in t and "mint" in t and ("next month" in t or "nextmonth" in t or "next-month" in t))
    has_due = "2026-03-13" in t
    return alex_ok and jamie_ok and pat_ok and has_due


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "compute_weekly_borrows_correct": 0.0,
        "csv_output_valid": 0.0,
        "json_output_valid": 0.0,
        "docs_dir_overview_complete": 0.0,
        "docs_meeting_notes_decisions": 0.0,
        "docs_meeting_notes_action_items": 0.0,
    }

    records, include_herbs = _load_workspace_records_and_config(workspace)
    expected_rows: Optional[List[Dict[str, Any]]] = None
    if records is not None and include_herbs is not None:
        expected_rows = _compute_expected_summary(records, include_herbs)

    student_mod = _import_student_module(workspace)
    if student_mod is not None and expected_rows is not None:
        try:
            student_rows = student_mod.compute_weekly_borrows(records, include_herbs)
            if isinstance(student_rows, list) and _rows_equal(expected_rows, student_rows):
                scores["compute_weekly_borrows_correct"] = 1.0
        except Exception:
            scores["compute_weekly_borrows_correct"] = 0.0

    if expected_rows is not None:
        csv_out = workspace / "output" / "weekly_summary.csv"
        json_out = workspace / "output" / "weekly_summary.json"
        if _validate_csv_output(csv_out, expected_rows):
            scores["csv_output_valid"] = 1.0
        if _validate_json_output(json_out, expected_rows):
            scores["json_output_valid"] = 1.0

    dir_overview_path = workspace / "docs" / "dir_overview.txt"
    dir_overview_text = _safe_read_text(dir_overview_path)
    expected_files = _list_all_expected_files(workspace)
    if dir_overview_text is not None and expected_files:
        if _parse_dir_overview_for_sizes(dir_overview_text, expected_files, workspace):
            scores["docs_dir_overview_complete"] = 1.0

    meeting_notes_path = workspace / "docs" / "meeting_notes.md"
    meeting_notes_text = _safe_read_text(meeting_notes_path)
    if _check_meeting_notes_decisions(meeting_notes_text or ""):
        scores["docs_meeting_notes_decisions"] = 1.0
    if _check_meeting_notes_action_items(meeting_notes_text or ""):
        scores["docs_meeting_notes_action_items"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()