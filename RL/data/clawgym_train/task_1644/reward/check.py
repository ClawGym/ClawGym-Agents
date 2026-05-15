import sys
import json
import csv
import ast
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return None


def _load_column_map(workspace: Path) -> Optional[Dict[str, str]]:
    script_path = workspace / "scripts" / "etl_template.py"
    source = _read_text_safe(script_path)
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except Exception:
        return None
    col_map = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "COLUMN_MAP":
                    try:
                        value = ast.literal_eval(node.value)
                        if isinstance(value, dict):
                            tmp = {}
                            for k, v in value.items():
                                if isinstance(k, str) and isinstance(v, str):
                                    tmp[k] = v
                            col_map = tmp
                    except Exception:
                        return None
    return col_map


def _load_thresholds_yaml(workspace: Path) -> Optional[Dict[str, Dict[str, float]]]:
    path = workspace / "config" / "vitals_thresholds.yaml"
    text = _read_text_safe(path)
    if text is None:
        return None
    result: Dict[str, Dict[str, float]] = {}
    current_key: Optional[str] = None
    try:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith(":") and not line.startswith(("min:", "max:")):
                current_key = line[:-1].strip()
                result[current_key] = {}
                continue
            if ":" in line and current_key is not None:
                k, v = line.split(":", 1)
                key = k.strip()
                val = v.strip()
                if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
                    val = val[1:-1]
                try:
                    num = float(val)
                except Exception:
                    return None
                result[current_key][key] = num
        required_vitals = ["heart_rate", "systolic_bp", "diastolic_bp", "temperature_c"]
        for vital in required_vitals:
            if vital not in result:
                return None
            if "min" not in result[vital] or "max" not in result[vital]:
                return None
        return result
    except Exception:
        return None


def _discover_input_csvs(workspace: Path) -> List[Path]:
    base = workspace / "input" / "clinics"
    if not base.exists():
        return []
    return sorted([p for p in base.rglob("*.csv") if p.is_file()])


def _read_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [row for row in reader]
            return headers, rows
    except UnicodeDecodeError:
        try:
            with path.open("r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                if headers is None:
                    return None, None
                rows = [row for row in reader]
                return headers, rows
        except Exception:
            return None, None
    except Exception:
        return None, None


def _parse_utc_iso(ts: str) -> Optional[datetime]:
    if ts is None:
        return None
    s = ts.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _canonical_required_columns() -> List[str]:
    return [
        "heart_rate",
        "systolic_bp",
        "diastolic_bp",
        "temperature_c",
        "timestamp",
        "site",
    ]


def _normalize_source_path(workspace: Path, p: Path) -> str:
    try:
        rel = p.relative_to(workspace)
    except ValueError:
        rel = p
    return rel.as_posix().lstrip("./")


def _compare_paths_rel(actual: str, expected_rel: str) -> bool:
    act = actual.replace("\\", "/").lstrip("./")
    exp = expected_rel.replace("\\", "/").lstrip("./")
    return act == exp or act.endswith("/" + exp) or exp.endswith("/" + act)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_csv_exists_and_header": 0.0,
        "summary_content_correct": 0.0,
        "abnormal_events_jsonl_exists_and_format": 0.0,
        "abnormal_events_content_correct": 0.0,
        "schema_audit_exists_and_header": 0.0,
        "schema_audit_content_correct": 0.0,
        "audit_covers_all_input_csvs": 0.0,
    }

    column_map = _load_column_map(workspace)
    thresholds = _load_thresholds_yaml(workspace)
    input_csvs = _discover_input_csvs(workspace)

    expected_summary: Dict[Tuple[str, int, int], Dict[str, int]] = {}
    expected_events: List[Dict[str, Any]] = []
    expected_audit: Dict[str, Dict[str, Any]] = {}

    if column_map is not None and thresholds is not None:
        required = _canonical_required_columns()
        for csv_path in input_csvs:
            headers, rows = _read_csv_safe(csv_path)
            if headers is None or rows is None:
                continue
            canonical_to_source: Dict[str, str] = {}
            for h in headers:
                if h in column_map:
                    canon = column_map[h]
                    if canon not in canonical_to_source:
                        canonical_to_source[canon] = h
            columns_found = ",".join(headers)
            unmapped_cols = [h for h in headers if h not in column_map]
            missing_canon = [c for c in required if c not in canonical_to_source]
            invalid_rows = 0
            total_rows = len(rows)

            for row in rows:
                hr = _to_float(row.get(canonical_to_source.get("heart_rate", "")))
                sbp = _to_float(row.get(canonical_to_source.get("systolic_bp", "")))
                dbp = _to_float(row.get(canonical_to_source.get("diastolic_bp", "")))
                temp = _to_float(row.get(canonical_to_source.get("temperature_c", "")))
                ts_raw = row.get(canonical_to_source.get("timestamp", ""), None)
                site_val = row.get(canonical_to_source.get("site", ""), None)

                if (
                    hr is None
                    or sbp is None
                    or dbp is None
                    or temp is None
                ):
                    invalid_rows += 1
                    continue
                dt = _parse_utc_iso(ts_raw) if ts_raw is not None else None
                if dt is None or site_val is None or str(site_val).strip() == "":
                    invalid_rows += 1
                    continue

                abnormal_fields: List[str] = []
                if hr < thresholds["heart_rate"]["min"] or hr > thresholds["heart_rate"]["max"]:
                    abnormal_fields.append("heart_rate")
                if sbp < thresholds["systolic_bp"]["min"] or sbp > thresholds["systolic_bp"]["max"]:
                    abnormal_fields.append("systolic_bp")
                if dbp < thresholds["diastolic_bp"]["min"] or dbp > thresholds["diastolic_bp"]["max"]:
                    abnormal_fields.append("diastolic_bp")
                if temp < thresholds["temperature_c"]["min"] or temp > thresholds["temperature_c"]["max"]:
                    abnormal_fields.append("temperature_c")

                iso_year, iso_week, _ = dt.isocalendar()
                key = (str(site_val), int(iso_year), int(iso_week))
                if key not in expected_summary:
                    expected_summary[key] = {
                        "total_readings": 0,
                        "abnormal_any": 0,
                        "abnormal_heart_rate": 0,
                        "abnormal_systolic_bp": 0,
                        "abnormal_diastolic_bp": 0,
                        "abnormal_temperature_c": 0,
                    }
                expected_summary[key]["total_readings"] += 1
                if abnormal_fields:
                    expected_summary[key]["abnormal_any"] += 1
                    if "heart_rate" in abnormal_fields:
                        expected_summary[key]["abnormal_heart_rate"] += 1
                    if "systolic_bp" in abnormal_fields:
                        expected_summary[key]["abnormal_systolic_bp"] += 1
                    if "diastolic_bp" in abnormal_fields:
                        expected_summary[key]["abnormal_diastolic_bp"] += 1
                    if "temperature_c" in abnormal_fields:
                        expected_summary[key]["abnormal_temperature_c"] += 1
                    expected_events.append({
                        "site": str(site_val),
                        "timestamp_raw": ts_raw,
                        "timestamp_dt": dt,
                        "heart_rate": hr,
                        "systolic_bp": sbp,
                        "diastolic_bp": dbp,
                        "temperature_c": temp,
                        "abnormal_fields": sorted(abnormal_fields),
                        "source_file": _normalize_source_path(workspace, csv_path),
                    })

            expected_audit[_normalize_source_path(workspace, csv_path)] = {
                "file_path": _normalize_source_path(workspace, csv_path),
                "total_rows": total_rows,
                "invalid_rows": invalid_rows,
                "columns_found": columns_found,
                "unmapped_columns": ",".join(unmapped_cols),
                "missing_canonical_columns": ",".join(missing_canon),
            }

    summary_path = workspace / "results" / "summary.csv"
    summary_headers, summary_rows = _read_csv_safe(summary_path)
    required_summary_fields = [
        "site",
        "year",
        "iso_week",
        "total_readings",
        "abnormal_any",
        "abnormal_heart_rate",
        "abnormal_systolic_bp",
        "abnormal_diastolic_bp",
        "abnormal_temperature_c",
    ]
    if summary_headers is not None and summary_rows is not None:
        if summary_headers == required_summary_fields:
            scores["summary_csv_exists_and_header"] = 1.0
        else:
            scores["summary_csv_exists_and_header"] = 0.0
    else:
        scores["summary_csv_exists_and_header"] = 0.0

    if summary_headers is not None and summary_rows is not None and column_map is not None and thresholds is not None:
        actual_summary: Dict[Tuple[str, int, int], Dict[str, int]] = {}
        try:
            for row in summary_rows:
                site = row.get("site", "")
                try:
                    year = int(row.get("year", "0"))
                    iso_week = int(row.get("iso_week", "0"))
                    tr = int(row.get("total_readings", "0"))
                    ab_any = int(row.get("abnormal_any", "0"))
                    ab_hr = int(row.get("abnormal_heart_rate", "0"))
                    ab_sbp = int(row.get("abnormal_systolic_bp", "0"))
                    ab_dbp = int(row.get("abnormal_diastolic_bp", "0"))
                    ab_temp = int(row.get("abnormal_temperature_c", "0"))
                except Exception:
                    actual_summary = {}
                    break
                key = (site, year, iso_week)
                actual_summary[key] = {
                    "total_readings": tr,
                    "abnormal_any": ab_any,
                    "abnormal_heart_rate": ab_hr,
                    "abnormal_systolic_bp": ab_sbp,
                    "abnormal_diastolic_bp": ab_dbp,
                    "abnormal_temperature_c": ab_temp,
                }
            if expected_summary and actual_summary == expected_summary:
                scores["summary_content_correct"] = 1.0
            else:
                if not expected_summary and not actual_summary:
                    scores["summary_content_correct"] = 1.0
                else:
                    scores["summary_content_correct"] = 0.0
        except Exception:
            scores["summary_content_correct"] = 0.0
    else:
        scores["summary_content_correct"] = 0.0

    events_path = workspace / "results" / "abnormal_events.jsonl"
    events_lines: List[str] = []
    student_events: List[Dict[str, Any]] = []
    if events_path.exists() and events_path.is_file():
        text = _read_text_safe(events_path)
        if text is not None:
            events_lines = [ln for ln in text.splitlines() if ln.strip() != ""]
            parse_ok = True
            for ln in events_lines:
                try:
                    obj = json.loads(ln)
                    if not isinstance(obj, dict):
                        parse_ok = False
                        break
                    required_event_keys = {
                        "site",
                        "timestamp",
                        "heart_rate",
                        "systolic_bp",
                        "diastolic_bp",
                        "temperature_c",
                        "abnormal_fields",
                        "source_file",
                    }
                    if not required_event_keys.issubset(set(obj.keys())):
                        parse_ok = False
                        break
                    if not isinstance(obj.get("abnormal_fields"), list):
                        parse_ok = False
                        break
                    student_events.append(obj)
                except Exception:
                    parse_ok = False
                    break
            if parse_ok:
                scores["abnormal_events_jsonl_exists_and_format"] = 1.0
            else:
                scores["abnormal_events_jsonl_exists_and_format"] = 0.0
        else:
            scores["abnormal_events_jsonl_exists_and_format"] = 0.0
    else:
        scores["abnormal_events_jsonl_exists_and_format"] = 0.0

    if column_map is not None and thresholds is not None and student_events is not None:
        try:
            unmatched_student = list(range(len(student_events)))
            matched_all = True

            def _find_match(exp_ev: Dict[str, Any]) -> Optional[int]:
                for idx in unmatched_student:
                    ev = student_events[idx]
                    if str(ev.get("site")) != str(exp_ev["site"]):
                        continue
                    dt_student = _parse_utc_iso(str(ev.get("timestamp")))
                    if dt_student is None or abs(int(dt_student.timestamp()) - int(exp_ev["timestamp_dt"].timestamp())) != 0:
                        continue
                    hr_s = _to_float(ev.get("heart_rate"))
                    sbp_s = _to_float(ev.get("systolic_bp"))
                    dbp_s = _to_float(ev.get("diastolic_bp"))
                    temp_s = _to_float(ev.get("temperature_c"))
                    if hr_s is None or sbp_s is None or dbp_s is None or temp_s is None:
                        continue
                    tol = 1e-9
                    if not (abs(hr_s - exp_ev["heart_rate"]) <= tol and
                            abs(sbp_s - exp_ev["systolic_bp"]) <= tol and
                            abs(dbp_s - exp_ev["diastolic_bp"]) <= tol and
                            abs(temp_s - exp_ev["temperature_c"]) <= tol):
                        continue
                    af_student = ev.get("abnormal_fields")
                    if not isinstance(af_student, list):
                        continue
                    if set(af_student) != set(exp_ev["abnormal_fields"]):
                        continue
                    sf = str(ev.get("source_file", ""))
                    if not _compare_paths_rel(sf, exp_ev["source_file"]):
                        continue
                    return idx
                return None

            if expected_events:
                for exp in expected_events:
                    mi = _find_match(exp)
                    if mi is None:
                        matched_all = False
                        break
                    else:
                        unmatched_student.remove(mi)
                if matched_all and len(unmatched_student) == 0:
                    scores["abnormal_events_content_correct"] = 1.0
                else:
                    scores["abnormal_events_content_correct"] = 0.0
            else:
                if len(student_events) == 0:
                    scores["abnormal_events_content_correct"] = 1.0
                else:
                    scores["abnormal_events_content_correct"] = 0.0
        except Exception:
            scores["abnormal_events_content_correct"] = 0.0
    else:
        scores["abnormal_events_content_correct"] = 0.0

    audit_path = workspace / "results" / "schema_audit.csv"
    audit_headers, audit_rows = _read_csv_safe(audit_path)
    required_audit_fields = [
        "file_path",
        "total_rows",
        "invalid_rows",
        "columns_found",
        "unmapped_columns",
        "missing_canonical_columns",
    ]
    if audit_headers is not None and audit_rows is not None:
        if audit_headers == required_audit_fields:
            scores["schema_audit_exists_and_header"] = 1.0
        else:
            scores["schema_audit_exists_and_header"] = 0.0
    else:
        scores["schema_audit_exists_and_header"] = 0.0

    if audit_headers is not None and audit_rows is not None and column_map is not None and thresholds is not None:
        try:
            student_audit: Dict[str, Dict[str, Any]] = {}
            for row in audit_rows:
                fp = (row.get("file_path") or "").replace("\\", "/").lstrip("./")
                if fp == "":
                    continue
                student_audit[fp] = {
                    "file_path": fp,
                    "total_rows": row.get("total_rows"),
                    "invalid_rows": row.get("invalid_rows"),
                    "columns_found": row.get("columns_found"),
                    "unmapped_columns": row.get("unmapped_columns"),
                    "missing_canonical_columns": row.get("missing_canonical_columns"),
                }
            expected_paths_set = set(expected_audit.keys())
            student_paths_set = set(student_audit.keys())
            if expected_paths_set == student_paths_set:
                scores["audit_covers_all_input_csvs"] = 1.0
            else:
                if not expected_paths_set and not student_paths_set:
                    scores["audit_covers_all_input_csvs"] = 1.0
                else:
                    scores["audit_covers_all_input_csvs"] = 0.0

            content_ok = True
            if expected_paths_set != student_paths_set:
                content_ok = False
            else:
                for fp in expected_paths_set:
                    exp = expected_audit[fp]
                    stu = student_audit.get(fp, {})
                    try:
                        tr_exp = int(exp["total_rows"])
                        ir_exp = int(exp["invalid_rows"])
                        tr_stu = int(stu.get("total_rows", "-1"))
                        ir_stu = int(stu.get("invalid_rows", "-1"))
                    except Exception:
                        content_ok = False
                        break
                    if tr_exp != tr_stu or ir_exp != ir_stu:
                        content_ok = False
                        break
                    if (stu.get("columns_found") or "") != (exp["columns_found"] or ""):
                        content_ok = False
                        break
                    if (stu.get("unmapped_columns") or "") != (exp["unmapped_columns"] or ""):
                        content_ok = False
                        break
                    if (stu.get("missing_canonical_columns") or "") != (exp["missing_canonical_columns"] or ""):
                        content_ok = False
                        break
            if content_ok:
                scores["schema_audit_content_correct"] = 1.0
            else:
                if not expected_audit and not student_audit:
                    scores["schema_audit_content_correct"] = 1.0
                else:
                    scores["schema_audit_content_correct"] = 0.0
        except Exception:
            scores["schema_audit_content_correct"] = 0.0
    else:
        scores["schema_audit_content_correct"] = 0.0

    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()