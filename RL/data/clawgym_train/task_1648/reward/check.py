import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            headers = reader.fieldnames if reader.fieldnames is not None else []
            return rows, headers, None
    except Exception as e:
        return None, None, str(e)


def _parse_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _parse_int(val: Any) -> Optional[int]:
    f = _parse_float(val)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def _parse_bool_str(val: Any) -> Optional[bool]:
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in ("true", "t", "1", "yes", "y"):
        return True
    if s in ("false", "f", "0", "no", "n"):
        return False
    if s == "":
        return None
    return None


def _clinic_note_extract(note_html: str) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    li_pattern = re.compile(r"<li>(.*?)</li>", re.IGNORECASE | re.DOTALL)
    items = li_pattern.findall(note_html)
    if not items:
        items = [l for l in note_html.splitlines() if "Session:" in l]

    for item in items:
        text = re.sub(r"<[^>]+>", " ", item)
        text = re.sub(r"\s+", " ", text).strip()
        m = re.search(r"Session:\s*(S\d+)", text, re.IGNORECASE)
        if not m:
            continue
        session_id = m.group(1).upper()

        step_m = re.search(r"Recorded step_count:\s*(\d+)", text, re.IGNORECASE)
        step_count = int(step_m.group(1)) if step_m else None

        lower = text.lower()
        adverse = False
        keywords = set()
        if "near-fall" in lower or "near fall" in lower:
            adverse = True
            keywords.add("near-fall")
        if "assisted" in lower:
            adverse = True
            keywords.add("assisted")
        if "unable to compute" in lower:
            adverse = True
            keywords.add("unable to compute")
        if "adverse" in lower and "no adverse" not in lower:
            adverse = True
            keywords.add("adverse")
        if "artifact" in lower:
            keywords.add("artifact")
        results[session_id] = {
            "step_count": step_count,
            "adverse": adverse,
            "keywords": keywords,
        }
    return results


def _select_norm_bracket(norms: List[Dict[str, Any]], age: Optional[int]) -> Optional[Dict[str, Any]]:
    if age is None:
        return None
    for bracket in norms:
        try:
            amin = int(bracket.get("age_min", -10**9))
            amax = int(bracket.get("age_max", 10**9))
        except Exception:
            continue
        if amin <= age <= amax:
            return bracket
    return None


def _cmp_float(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if (a is None) != (b is None):
        return False
    return abs(float(a) - float(b)) <= tol


def _expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    gait_path = workspace / "input" / "gait_sessions.csv"
    registry_path = workspace / "input" / "patient_registry.json"
    norms_path = workspace / "input" / "norms.json"
    clinic_path = workspace / "input" / "clinic_note.html"

    gait_rows, gait_headers, gait_err = _safe_read_csv_dicts(gait_path)
    registry, reg_err = _safe_load_json(registry_path)
    norms, norms_err = _safe_load_json(norms_path)
    clinic_html, clinic_err = _safe_read_text(clinic_path)

    if gait_rows is None or registry is None or norms is None or clinic_html is None:
        return None

    age_map: Dict[str, int] = {}
    try:
        for rec in registry:
            pid = rec.get("patient_id")
            age = rec.get("age")
            if isinstance(pid, str) and isinstance(age, int):
                age_map[pid] = age
    except Exception:
        return None

    stride_norms = norms.get("stride_time_ms", [])
    valid_devices = norms.get("valid_devices", [])
    if not isinstance(stride_norms, list) or not isinstance(valid_devices, list):
        return None

    clinic = _clinic_note_extract(clinic_html)

    expected: Dict[str, Any] = {
        "sessions": {},
        "patients_set": set(),
        "per_task": {},
        "valid_devices": set(valid_devices),
    }

    for row in gait_rows:
        sid = str(row.get("session_id", "")).strip()
        pid = str(row.get("patient_id", "")).strip()
        task = str(row.get("task", "")).strip()
        device = str(row.get("device", "")).strip()
        expected["patients_set"].add(pid)

        stride_mean = _parse_float(row.get("stride_time_ms"))
        stride_sd = _parse_float(row.get("stride_time_sd_ms"))
        if stride_mean is not None and stride_sd is not None and stride_mean != 0:
            stride_cv = stride_sd / stride_mean
        else:
            stride_cv = None

        age = age_map.get(pid)
        bracket = _select_norm_bracket(stride_norms, age)
        within_norms = None
        if stride_mean is not None and stride_cv is not None and bracket is not None:
            try:
                max_mean = float(bracket.get("max_mean"))
                max_cv = float(bracket.get("max_cv"))
                within_norms = (stride_mean <= max_mean) and (stride_cv <= max_cv)
            except Exception:
                within_norms = None

        clinic_info = clinic.get(sid, {})
        clinic_step = clinic_info.get("step_count")
        clinic_adverse = bool(clinic_info.get("adverse", False))
        clinic_keywords = clinic_info.get("keywords", set())

        csv_step = _parse_int(row.get("step_count"))
        step_mismatch = False
        if clinic_step is not None and csv_step is not None and clinic_step != csv_step:
            step_mismatch = True

        flags = set()
        if stride_mean is None or stride_sd is None:
            flags.add("missing_stride_metrics")
        if step_mismatch:
            flags.add("step_count_mismatch")
        if clinic_adverse:
            flags.add("adverse_event_reported")
        if device and (device not in valid_devices):
            flags.add("device_invalid")

        expected["sessions"][sid] = {
            "session_id": sid,
            "patient_id": pid,
            "age": age,
            "task": task,
            "stride_time_ms": stride_mean,
            "stride_time_cv": stride_cv,
            "step_count": csv_step,
            "device": device,
            "within_norms": within_norms,
            "flags": flags,
            "adverse_keywords": clinic_keywords,
        }

    per_task: Dict[str, Dict[str, Any]] = {}
    for sess in expected["sessions"].values():
        t = sess["task"]
        if t not in per_task:
            per_task[t] = {
                "count": 0,
                "stride_values": [],
                "count_within_norms": 0,
            }
        per_task[t]["count"] += 1
        if isinstance(sess.get("stride_time_ms"), (int, float)):
            per_task[t]["stride_values"].append(float(sess["stride_time_ms"]))
        if sess.get("within_norms") is True:
            per_task[t]["count_within_norms"] += 1

    per_task_summary = {}
    for t, d in per_task.items():
        if d["stride_values"]:
            mean_val = sum(d["stride_values"]) / len(d["stride_values"])
        else:
            mean_val = None
        per_task_summary[t] = {
            "count": d["count"],
            "mean_stride_time_ms": mean_val,
            "count_within_norms": d["count_within_norms"],
        }

    expected["summary"] = {
        "total_patients": len(expected["patients_set"]),
        "total_sessions": len(expected["sessions"]),
        "sessions_within_norms": sum(1 for s in expected["sessions"].values() if s.get("within_norms") is True),
        "sessions_flagged": sum(1 for s in expected["sessions"].values() if s.get("flags")),
        "per_task": per_task_summary,
    }

    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "cleaned_sessions_exists": 0.0,
        "cleaned_sessions_columns_order": 0.0,
        "cleaned_sessions_row_count": 0.0,
        "age_attached": 0.0,
        "cleaned_sessions_cv_and_within_norms": 0.0,
        "flags_correct": 0.0,
        "notes_presence_for_adverse": 0.0,
        "devices_validated_in_cleaned": 0.0,
        "summary_exists_structure": 0.0,
        "summary_counts_correct": 0.0,
        "summary_per_task_correct": 0.0,
        "status_report_exists": 0.0,
        "status_report_counts_and_length": 0.0,
        "status_report_flagged_and_missing": 0.0,
        "status_report_within_norms_by_task": 0.0,
    }

    expected = _expected_from_inputs(workspace)
    cleaned_path = workspace / "output" / "cleaned_sessions.csv"
    summary_path = workspace / "output" / "summary.json"
    status_path = workspace / "output" / "status_report.md"

    cleaned_rows, cleaned_headers, cleaned_err = _safe_read_csv_dicts(cleaned_path)
    if cleaned_rows is None or cleaned_headers is None:
        return scores
    scores["cleaned_sessions_exists"] = 1.0

    required_headers = [
        "session_id",
        "patient_id",
        "age",
        "task",
        "stride_time_ms",
        "stride_time_cv",
        "step_count",
        "device",
        "within_norms",
        "notes",
        "flags",
    ]
    if cleaned_headers == required_headers:
        scores["cleaned_sessions_columns_order"] = 1.0

    cleaned_by_sid: Dict[str, Dict[str, str]] = {}
    for row in cleaned_rows:
        sid = str(row.get("session_id", "")).strip()
        if sid:
            cleaned_by_sid[sid] = row

    if expected is not None:
        expected_sids = set(expected["sessions"].keys())
        if set(cleaned_by_sid.keys()) == expected_sids and len(cleaned_rows) == len(expected_sids):
            scores["cleaned_sessions_row_count"] = 1.0

    age_ok = False
    cv_ok = False
    flags_ok = False
    notes_ok = False
    devices_ok = False

    if expected is not None:
        age_ok = True
        cv_ok = True
        flags_ok = True
        notes_ok = True
        devices_ok = True

        for sid, exp in expected["sessions"].items():
            row = cleaned_by_sid.get(sid)
            if row is None:
                age_ok = False
                cv_ok = False
                flags_ok = False
                notes_ok = False
                devices_ok = False
                break

            got_age = _parse_int(row.get("age"))
            if got_age != exp["age"]:
                age_ok = False

            got_cv = _parse_float(row.get("stride_time_cv"))
            got_mean = _parse_float(row.get("stride_time_ms"))
            exp_cv = exp["stride_time_cv"]
            exp_mean = exp["stride_time_ms"]
            if not _cmp_float(got_mean, exp_mean):
                cv_ok = False
            if not _cmp_float(got_cv, exp_cv):
                cv_ok = False

            got_within = _parse_bool_str(row.get("within_norms"))
            if exp["within_norms"] is None:
                within_field = str(row.get("within_norms", "")).strip()
                if within_field != "":
                    cv_ok = False
            else:
                if got_within is None or bool(got_within) != bool(exp["within_norms"]):
                    cv_ok = False

            got_flags_raw = str(row.get("flags", "") or "").strip()
            got_flags_set = set([f.strip() for f in got_flags_raw.split(";") if f.strip()])
            if got_flags_set != set(exp["flags"]):
                flags_ok = False

            got_device = str(row.get("device", "")).strip()
            if got_device != exp["device"]:
                devices_ok = False
            if "device_invalid" in got_flags_set and got_device in expected["valid_devices"]:
                devices_ok = False

            if exp["flags"] and ("adverse_event_reported" in exp["flags"]):
                notes_field = str(row.get("notes", "") or "").strip()
                if notes_field == "":
                    notes_ok = False
                else:
                    lower_notes = notes_field.lower()
                    indicative = False
                    for kw in ["near", "assist", "unable", "artifact"]:
                        if kw in lower_notes:
                            indicative = True
                            break
                    if not indicative:
                        notes_ok = False

    scores["age_attached"] = 1.0 if age_ok else 0.0
    scores["cleaned_sessions_cv_and_within_norms"] = 1.0 if cv_ok else 0.0
    scores["flags_correct"] = 1.0 if flags_ok else 0.0
    scores["notes_presence_for_adverse"] = 1.0 if notes_ok else 0.0
    scores["devices_validated_in_cleaned"] = 1.0 if devices_ok else 0.0

    summary_data, summary_err = _safe_load_json(summary_path)
    if summary_data is None:
        return scores
    scores["summary_exists_structure"] = 1.0

    required_summary_keys = ["total_patients", "total_sessions", "sessions_within_norms", "sessions_flagged", "per_task"]
    structure_ok = all(k in summary_data for k in required_summary_keys) and isinstance(summary_data.get("per_task"), dict)
    if not structure_ok:
        return scores

    if expected is not None:
        counts_ok = True
        try:
            if int(summary_data.get("total_patients")) != int(expected["summary"]["total_patients"]):
                counts_ok = False
            if int(summary_data.get("total_sessions")) != int(expected["summary"]["total_sessions"]):
                counts_ok = False
            if int(summary_data.get("sessions_within_norms")) != int(expected["summary"]["sessions_within_norms"]):
                counts_ok = False
            if int(summary_data.get("sessions_flagged")) != int(expected["summary"]["sessions_flagged"]):
                counts_ok = False
        except Exception:
            counts_ok = False
        scores["summary_counts_correct"] = 1.0 if counts_ok else 0.0

        per_task_ok = True
        for task, exp_vals in expected["summary"]["per_task"].items():
            got = summary_data["per_task"].get(task)
            if got is None:
                per_task_ok = False
                break
            try:
                if int(got.get("count")) != int(exp_vals["count"]):
                    per_task_ok = False
                if int(got.get("count_within_norms")) != int(exp_vals["count_within_norms"]):
                    per_task_ok = False
                got_mean = got.get("mean_stride_time_ms")
                exp_mean = exp_vals["mean_stride_time_ms"]
                if exp_mean is None:
                    if got_mean is not None:
                        per_task_ok = False
                else:
                    if _parse_float(got_mean) is None or not _cmp_float(_parse_float(got_mean), float(exp_mean)):
                        per_task_ok = False
            except Exception:
                per_task_ok = False
        scores["summary_per_task_correct"] = 1.0 if per_task_ok else 0.0

    status_text, status_err = _safe_read_text(status_path)
    if status_text is None:
        return scores
    scores["status_report_exists"] = 1.0

    text_lower = status_text.lower()
    words = re.findall(r"\b\w+\b", status_text)
    length_ok = len(words) <= 300
    counts_present = ("patient" in text_lower) and ("session" in text_lower)
    counts_ok_simple = False
    if expected is not None:
        tp = expected["summary"]["total_patients"]
        ts = expected["summary"]["total_sessions"]
        counts_ok_simple = (str(tp) in status_text) and (str(ts) in status_text)
    scores["status_report_counts_and_length"] = 1.0 if (length_ok and counts_present and counts_ok_simple) else 0.0

    flagged_ok = False
    missing_ok = False
    if expected is not None:
        has_s003 = "s003" in text_lower
        has_s004 = "s004" in text_lower
        has_mismatch = "mismatch" in text_lower
        has_adverse = "adverse" in text_lower
        flagged_ok = has_s003 and has_s004 and has_mismatch and has_adverse

        has_missing = ("missing" in text_lower and "stride" in text_lower and "metric" in text_lower) or ("unable to compute" in text_lower)
        has_recommendation = any(w in text_lower for w in ["recommend", "suggest", "repeat", "re-run", "rerun", "reassess", "retest", "recalibrate"])
        missing_ok = has_missing and has_recommendation

    scores["status_report_flagged_and_missing"] = 1.0 if (flagged_ok and missing_ok) else 0.0

    within_norms_ok = ("within" in text_lower and "norm" in text_lower)
    tasks_present = all(t in text_lower for t in ["10m_walk", "timed_up_and_go"])
    scores["status_report_within_norms_by_task"] = 1.0 if (within_norms_ok and tasks_present) else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()