import json
import csv
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Very simple YAML parser for key: value pairs, handling quoted strings and integers.
    Intended for the provided profile.yaml format.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove comments after value
            if "#" in val:
                val = val.split("#", 1)[0].strip()
            # Remove surrounding quotes if present
            if ((val.startswith('"') and val.endswith('"')) or
                (val.startswith("'") and val.endswith("'"))):
                val_unquoted = val[1:-1]
            else:
                val_unquoted = val
            # Try to coerce to int if purely numeric
            v: Any = val_unquoted
            try:
                if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
                    v = int(v)
            except Exception:
                pass
            data[key] = v
        return data
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: Path, obj: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _to_int(value: Any) -> Optional[int]:
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        s = str(value).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, float):
            return value
        if isinstance(value, int):
            return float(value)
        s = str(value).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _parse_bool_str(s: Any) -> Optional[bool]:
    if isinstance(s, bool):
        return s
    try:
        val = str(s).strip().lower()
    except Exception:
        return None
    if val in ("true", "1", "yes", "y", "t"):
        return True
    if val in ("false", "0", "no", "n", "f"):
        return False
    return None


def _isclose(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _compute_alerts_for_session(session: Dict[str, Any],
                                predicted_max_hr: float,
                                lower_bound: float,
                                upper_bound: float,
                                symptom_keywords: List[str]) -> List[str]:
    reasons: List[str] = []
    avg_hr = _to_float(session.get("avg_hr"))
    max_hr = _to_float(session.get("max_hr"))
    perceived_exertion = _to_int(session.get("perceived_exertion"))
    notes = session.get("notes") or ""
    notes_l = str(notes).lower()
    if max_hr is not None:
        if max_hr >= 0.95 * predicted_max_hr:
            reasons.append("max_hr_over_95pct")
    if perceived_exertion is not None:
        if perceived_exertion >= 8:
            reasons.append("high_exertion")
    if avg_hr is not None:
        if avg_hr > upper_bound:
            reasons.append("avg_hr_above_upper_zone")
        elif avg_hr < lower_bound:
            reasons.append("avg_hr_below_lower_zone")
    for kw in symptom_keywords:
        if kw in notes_l:
            reasons.append(f"symptom_keyword:{kw}")
    return reasons


def _compute_preparedness_score(avg_hr: float, duration_min: float,
                                lower_bound: float, upper_bound: float) -> float:
    denom = (upper_bound - lower_bound)
    if denom <= 0:
        return 0.0
    ratio = (avg_hr - lower_bound) / denom
    factor = _clamp(ratio, 0.0, 1.0)
    return duration_min * factor


def _read_symptom_keywords(path: Path) -> Optional[List[str]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    kws: List[str] = []
    for line in text.splitlines():
        word = line.strip().lower()
        if not word:
            continue
        kws.append(word)
    return kws


def _identify_key(session: Dict[str, Any]) -> Tuple[str, str]:
    return (str(session.get("date", "")).strip(), str(session.get("activity", "")).strip())


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "summary_profile_correct": 0.0,
        "summary_derived_zone_correct": 0.0,
        "summary_counts_consistent": 0.0,
        "alerts_structure_and_fields": 0.0,
        "alerts_reasons_exact": 0.0,
        "top_sessions_columns_exact": 0.0,
        "top_sessions_count_and_eligibility": 0.0,
        "top_sessions_order_and_scores": 0.0,
        "validator_ran_ok": 0.0,
        "validation_log_matches_stdout": 0.0,
    }

    # Load inputs
    profile_yaml = workspace / "input" / "profile.yaml"
    hr_csv = workspace / "input" / "heart_rate_log.csv"
    symp_txt = workspace / "input" / "symptom_keywords.txt"

    profile = _load_simple_yaml(profile_yaml)
    csv_rows_raw = _load_csv_dicts(hr_csv)
    symptom_keywords = _read_symptom_keywords(symp_txt)

    # If any input missing, many checks cannot proceed
    if not (profile and isinstance(profile, dict) and
            csv_rows_raw is not None and
            symptom_keywords is not None):
        # still attempt validator check if present
        # Run validator
        try:
            validator_path = workspace / "tests" / "validate_outputs.py"
            if validator_path.exists():
                proc = subprocess.run([sys.executable, str(validator_path)], cwd=str(workspace),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout = proc.stdout.strip()
                # Check validation.log
                log_path = workspace / "outputs" / "validation.log"
                log_text = _safe_read_text(log_path)
                if stdout == "OK":
                    scores["validator_ran_ok"] = 1.0
                if log_text is not None and log_text.strip() == stdout:
                    scores["validation_log_matches_stdout"] = 1.0
        except Exception:
            pass
        return scores

    # Normalize input csv rows to typed dicts
    input_sessions: List[Dict[str, Any]] = []
    for row in csv_rows_raw:
        try:
            session = {
                "date": row.get("date", "").strip(),
                "activity": row.get("activity", "").strip(),
                "duration_min": _to_float(row.get("duration_min")),
                "avg_hr": _to_float(row.get("avg_hr")),
                "max_hr": _to_float(row.get("max_hr")),
                "perceived_exertion": _to_int(row.get("perceived_exertion")),
                "notes": row.get("notes", "") if row.get("notes") is not None else "",
            }
            if None in (session["duration_min"], session["avg_hr"], session["max_hr"], session["perceived_exertion"]):
                # Malformed numeric
                input_sessions = []
                break
            input_sessions.append(session)
        except Exception:
            input_sessions = []
            break

    if not input_sessions:
        # attempt validator checks only
        try:
            validator_path = workspace / "tests" / "validate_outputs.py"
            if validator_path.exists():
                proc = subprocess.run([sys.executable, str(validator_path)], cwd=str(workspace),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout = proc.stdout.strip()
                log_path = workspace / "outputs" / "validation.log"
                log_text = _safe_read_text(log_path)
                if stdout == "OK":
                    scores["validator_ran_ok"] = 1.0
                if log_text is not None and log_text.strip() == stdout:
                    scores["validation_log_matches_stdout"] = 1.0
        except Exception:
            pass
        return scores

    # Compute derived values
    age = profile.get("age")
    name = profile.get("name")
    if isinstance(age, int):
        predicted_max_hr = 220 - age
    else:
        predicted_max_hr = None

    lower_bound = None
    upper_bound = None
    if predicted_max_hr is not None:
        lower_bound = 0.60 * predicted_max_hr
        upper_bound = 0.85 * predicted_max_hr

    # Compute expected alerts
    expected_alerts_by_key: Dict[Tuple[str, str], List[str]] = {}
    for s in input_sessions:
        if predicted_max_hr is None or lower_bound is None or upper_bound is None:
            reasons = []
        else:
            reasons = _compute_alerts_for_session(s, float(predicted_max_hr), float(lower_bound), float(upper_bound), symptom_keywords)
        key = _identify_key(s)
        if reasons:
            expected_alerts_by_key[key] = reasons

    total_sessions = len(input_sessions)
    expected_alerts_count = len(expected_alerts_by_key)
    # Eligibility: duration >= 10 and zero alerts
    eligible_sessions = []
    for s in input_sessions:
        key = _identify_key(s)
        if s["duration_min"] is None:
            continue
        if s["duration_min"] >= 10 and key not in expected_alerts_by_key:
            eligible_sessions.append(s)
    expected_eligible_count = len(eligible_sessions)

    # Compute expected ranking
    expected_ranked_sorted: List[Tuple[Tuple[str, str], float]] = []
    if lower_bound is not None and upper_bound is not None:
        for s in eligible_sessions:
            score = _compute_preparedness_score(float(s["avg_hr"]), float(s["duration_min"]),
                                                float(lower_bound), float(upper_bound))
            expected_ranked_sorted.append((_identify_key(s), score))
        # Sort by score desc, then duration desc, then activity asc
        expected_ranked_sorted.sort(key=lambda kv: (-kv[1],
                                                    -_to_float(next(ss for ss in eligible_sessions if _identify_key(ss) == kv[0])["duration_min"]),
                                                    next(ss for ss in eligible_sessions if _identify_key(ss) == kv[0])["activity"]))
    expected_top_keys = [k for (k, _) in expected_ranked_sorted[:min(5, expected_eligible_count)]]

    # Load outputs
    summary_json_path = workspace / "outputs" / "summary.json"
    alerts_json_path = workspace / "outputs" / "alerts.json"
    top_sessions_csv_path = workspace / "outputs" / "top_sessions.csv"

    summary_obj = _load_json(summary_json_path)
    alerts_obj = _load_json(alerts_json_path)
    top_csv_rows: Optional[List[Dict[str, Any]]] = None
    top_csv_header: Optional[List[str]] = None
    try:
        if top_sessions_csv_path.exists():
            with top_sessions_csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                top_csv_header = reader.fieldnames
                top_csv_rows = []
                for row in reader:
                    top_csv_rows.append({k: v for k, v in row.items()})
    except Exception:
        top_csv_rows = None
        top_csv_header = None

    # summary_profile_correct
    try:
        prof = summary_obj.get("profile") if isinstance(summary_obj, dict) else None
        if isinstance(prof, dict):
            name_ok = (str(prof.get("name", "")).strip() == str(name).strip())
            age_ok = isinstance(prof.get("age"), int) and (prof.get("age") == age)
            if name_ok and age_ok:
                scores["summary_profile_correct"] = 1.0
    except Exception:
        pass

    # summary_derived_zone_correct
    try:
        derived = summary_obj.get("derived") if isinstance(summary_obj, dict) else None
        if derived and predicted_max_hr is not None and lower_bound is not None and upper_bound is not None:
            pmh = derived.get("predicted_max_hr")
            hr_zone = derived.get("hr_zone") if isinstance(derived.get("hr_zone"), dict) else None
            if pmh is not None and hr_zone is not None:
                pmh_ok = _to_int(pmh) == int(predicted_max_hr)
                lb = _to_float(hr_zone.get("lower_bound"))
                ub = _to_float(hr_zone.get("upper_bound"))
                lb_ok = (lb is not None and _isclose(lb, float(lower_bound)))
                ub_ok = (ub is not None and _isclose(ub, float(upper_bound)))
                if pmh_ok and lb_ok and ub_ok:
                    scores["summary_derived_zone_correct"] = 1.0
    except Exception:
        pass

    # alerts_structure_and_fields
    alerts_structure_ok = False
    if isinstance(alerts_obj, list):
        structure_valid = True
        for item in alerts_obj:
            if not isinstance(item, dict):
                structure_valid = False
                break
            req_fields = ["date", "activity", "duration_min", "avg_hr", "max_hr", "perceived_exertion", "reasons"]
            for f in req_fields:
                if f not in item:
                    structure_valid = False
                    break
            if not structure_valid:
                break
            # Types check
            if not isinstance(item.get("reasons"), list):
                structure_valid = False
                break
            # Ensure reasons are strings
            for r in item.get("reasons"):
                if not isinstance(r, str):
                    structure_valid = False
                    break
            # Numeric checks
            if _to_float(item.get("duration_min")) is None: structure_valid = False
            if _to_float(item.get("avg_hr")) is None: structure_valid = False
            if _to_float(item.get("max_hr")) is None: structure_valid = False
            if _to_int(item.get("perceived_exertion")) is None: structure_valid = False
            if not structure_valid:
                break
        if structure_valid:
            alerts_structure_ok = True
            scores["alerts_structure_and_fields"] = 1.0

    # alerts_reasons_exact
    try:
        if isinstance(alerts_obj, list) and alerts_structure_ok:
            # Build mapping from alerts.json
            alerts_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
            for item in alerts_obj:
                key = (str(item.get("date", "")).strip(), str(item.get("activity", "")).strip())
                alerts_by_key[key] = item
            expected_keys = set(expected_alerts_by_key.keys())
            got_keys = set(alerts_by_key.keys())
            if expected_keys == got_keys:
                # Check reasons and field consistency
                all_ok = True
                for key in expected_keys:
                    exp_reasons = sorted(expected_alerts_by_key[key])
                    got_item = alerts_by_key[key]
                    got_reasons = got_item.get("reasons", [])
                    if sorted(got_reasons) != exp_reasons:
                        all_ok = False
                        break
                    # Match base fields with input
                    # find session
                    sess = next((s for s in input_sessions if _identify_key(s) == key), None)
                    if not sess:
                        all_ok = False
                        break
                    if _to_float(got_item.get("duration_min")) != float(sess["duration_min"]):
                        all_ok = False
                        break
                    if _to_float(got_item.get("avg_hr")) != float(sess["avg_hr"]):
                        all_ok = False
                        break
                    if _to_float(got_item.get("max_hr")) != float(sess["max_hr"]):
                        all_ok = False
                        break
                    if _to_int(got_item.get("perceived_exertion")) != int(sess["perceived_exertion"]):
                        all_ok = False
                        break
                if all_ok:
                    scores["alerts_reasons_exact"] = 1.0
    except Exception:
        pass

    # summary_counts_consistent
    try:
        counts = summary_obj.get("counts") if isinstance(summary_obj, dict) else None
        if isinstance(counts, dict):
            total = _to_int(counts.get("total_sessions"))
            alerts_count = _to_int(counts.get("alerts_count"))
            eligible_for_ranking = _to_int(counts.get("eligible_for_ranking"))
            alerts_len = len(alerts_obj) if isinstance(alerts_obj, list) else None
            if (total == total_sessions and
                alerts_count == expected_alerts_count and
                alerts_len == expected_alerts_count and
                eligible_for_ranking == expected_eligible_count):
                scores["summary_counts_consistent"] = 1.0
    except Exception:
        pass

    # top_sessions_columns_exact
    expected_columns = ["date", "activity", "duration_min", "avg_hr", "perceived_exertion", "preparedness_score", "in_zone_avg"]
    if top_csv_header == expected_columns:
        scores["top_sessions_columns_exact"] = 1.0

    # top_sessions_count_and_eligibility
    try:
        if isinstance(top_csv_rows, list) and top_csv_header == expected_columns:
            row_count_ok = (len(top_csv_rows) == min(5, expected_eligible_count))
            none_have_alerts = True
            for row in top_csv_rows:
                key = (str(row.get("date", "")).strip(), str(row.get("activity", "")).strip())
                if key in expected_alerts_by_key:
                    none_have_alerts = False
                    break
            if row_count_ok and none_have_alerts:
                scores["top_sessions_count_and_eligibility"] = 1.0
    except Exception:
        pass

    # top_sessions_order_and_scores
    try:
        if isinstance(top_csv_rows, list) and top_csv_header == expected_columns and lower_bound is not None and upper_bound is not None:
            # Compare order and values
            got_keys_in_order = [(str(r.get("date", "")).strip(), str(r.get("activity", "")).strip()) for r in top_csv_rows]
            expected_top_keys_in_order = expected_top_keys
            order_ok = (got_keys_in_order == expected_top_keys_in_order)
            values_ok = True
            for r in top_csv_rows:
                key = (str(r.get("date", "")).strip(), str(r.get("activity", "")).strip())
                sess = next((s for s in input_sessions if _identify_key(s) == key), None)
                if not sess:
                    values_ok = False
                    break
                # Numeric fields exact match to input
                if _to_float(r.get("duration_min")) != float(sess["duration_min"]):
                    values_ok = False
                    break
                if _to_float(r.get("avg_hr")) != float(sess["avg_hr"]):
                    values_ok = False
                    break
                if _to_int(r.get("perceived_exertion")) != int(sess["perceived_exertion"]):
                    values_ok = False
                    break
                # in_zone_avg
                in_zone_expected = (float(sess["avg_hr"]) >= float(lower_bound) and float(sess["avg_hr"]) <= float(upper_bound))
                in_zone_csv_val = _parse_bool_str(r.get("in_zone_avg"))
                if in_zone_csv_val is None or in_zone_csv_val != in_zone_expected:
                    values_ok = False
                    break
                # preparedness_score rounded to 2 decimals
                score_full = _compute_preparedness_score(float(sess["avg_hr"]), float(sess["duration_min"]),
                                                         float(lower_bound), float(upper_bound))
                score_expected_rounded = round(score_full + 1e-12, 2)
                score_csv_val = _to_float(r.get("preparedness_score"))
                if score_csv_val is None or round(score_csv_val, 2) != score_expected_rounded:
                    values_ok = False
                    break
            if order_ok and values_ok:
                scores["top_sessions_order_and_scores"] = 1.0
    except Exception:
        pass

    # Validator checks
    try:
        validator_path = workspace / "tests" / "validate_outputs.py"
        if validator_path.exists():
            proc = subprocess.run([sys.executable, str(validator_path)], cwd=str(workspace),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout = proc.stdout.strip()
            if stdout == "OK":
                scores["validator_ran_ok"] = 1.0
            # Compare to validation.log
            log_path = workspace / "outputs" / "validation.log"
            log_text = _safe_read_text(log_path)
            if log_text is not None and log_text.strip() == stdout:
                scores["validation_log_matches_stdout"] = 1.0
    except Exception:
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()