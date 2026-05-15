import json
import sys
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _to_float(x: str) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _approx_equal(a: float, b: float, abs_tol: float = 0.05, rel_tol: float = 1e-3) -> bool:
    if a is None or b is None:
        return False
    diff = abs(a - b)
    return diff <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def _compute_means(values: List[float]) -> Optional[float]:
    if not values or any(v is None for v in values):
        return None
    return sum(values) / len(values)


def _compute_expected_biometrics(workspace: Path) -> Optional[dict]:
    baseline_path = workspace / "input" / "baseline_preseason.csv"
    training_path = workspace / "input" / "training_log.csv"
    baseline_rows, _ = _read_csv_dicts(baseline_path)
    training_rows, _ = _read_csv_dicts(training_path)
    if baseline_rows is None or training_rows is None:
        return None

    metrics = ["sleep_hours", "resting_hr", "hrv"]

    # Baseline means across all rows
    baseline_means = {}
    for m in metrics:
        vals = []
        for r in baseline_rows:
            v = _to_float(r.get(m, "").strip()) if r.get(m) is not None else None
            if v is None:
                return None
            vals.append(v)
        mean_v = _compute_means(vals)
        if mean_v is None:
            return None
        baseline_means[m] = mean_v

    # Last 7 days based on dates in training log
    dated_rows = []
    for r in training_rows:
        ds = r.get("date")
        if ds is None:
            return None
        d = _parse_date(ds)
        if d is None:
            return None
        dated_rows.append((d, r))
    if not dated_rows:
        return None
    dated_rows.sort(key=lambda x: x[0])
    dates_sorted = sorted({d for d, _ in dated_rows})
    last7_dates = dates_sorted[-7:] if len(dates_sorted) >= 7 else dates_sorted
    last7_set = set(last7_dates)

    last7_means = {}
    for m in metrics:
        vals = []
        for d, r in dated_rows:
            if d in last7_set:
                v = _to_float(r.get(m, "").strip()) if r.get(m) is not None else None
                if v is None:
                    return None
                vals.append(v)
        mean_v = _compute_means(vals)
        if mean_v is None:
            return None
        last7_means[m] = mean_v

    pct_changes = {}
    for m in metrics:
        b = baseline_means[m]
        l7 = last7_means[m]
        if b == 0:
            return None
        pct_changes[m] = ((l7 - b) / b) * 100.0

    return {
        "baseline_means": baseline_means,
        "last7_means": last7_means,
        "pct_changes": pct_changes,
        "last7_dates": [dt.strftime("%Y-%m-%d") for dt in last7_dates],
    }


def _compute_expected_training_load(workspace: Path) -> Optional[dict]:
    training_path = workspace / "input" / "training_log.csv"
    rows, _ = _read_csv_dicts(training_path)
    if rows is None:
        return None
    dated_rows = []
    for r in rows:
        ds = r.get("date")
        if ds is None:
            return None
        d = _parse_date(ds)
        if d is None:
            return None
        rpe = _to_float(r.get("rpe", "").strip()) if r.get("rpe") is not None else None
        minutes = _to_float(r.get("minutes_practice", "").strip()) if r.get("minutes_practice") is not None else None
        if rpe is None or minutes is None:
            return None
        daily_load = rpe * minutes
        dated_rows.append((d, daily_load))
    if len(dated_rows) < 14:
        # Need at least 14 days to form both windows
        return None
    dated_rows.sort(key=lambda x: x[0])
    dl = [dl for _, dl in dated_rows]
    acute_window = dl[-7:]
    chronic_window = dl[-14:-7]
    acute_total = sum(acute_window)
    chronic_total = sum(chronic_window)
    acute_avg = acute_total / 7.0
    chronic_avg = chronic_total / 7.0
    if chronic_avg == 0:
        ratio = None
    else:
        ratio = acute_avg / chronic_avg
    return {
        "acute_avg_load": acute_avg,
        "chronic_avg_load": chronic_avg,
        "ratio": ratio,
        "acute_total_load": acute_total,
        "chronic_total_load": chronic_total,
        "last7_dates": [d.strftime("%Y-%m-%d") for d, _ in dated_rows[-7:]],
        "prev7_dates": [d.strftime("%Y-%m-%d") for d, _ in dated_rows[-14:-7]],
    }


def _compute_expected_flagged_days(workspace: Path) -> Optional[Dict[str, List[str]]]:
    biometrics = _compute_expected_biometrics(workspace)
    if biometrics is None:
        return None
    training_path = workspace / "input" / "training_log.csv"
    rows, _ = _read_csv_dicts(training_path)
    if rows is None:
        return None

    baseline_hrv = biometrics["baseline_means"]["hrv"]
    baseline_rest = biometrics["baseline_means"]["resting_hr"]
    hrv_threshold = 0.85 * baseline_hrv
    rest_threshold = baseline_rest + 8.0
    last7_dates = set(biometrics["last7_dates"])

    flagged = {}
    for r in rows:
        date_str = r.get("date")
        if date_str is None or date_str not in last7_dates:
            continue
        reasons = []
        hrv = _to_float(r.get("hrv", "").strip()) if r.get("hrv") is not None else None
        sleep = _to_float(r.get("sleep_hours", "").strip()) if r.get("sleep_hours") is not None else None
        rest = _to_float(r.get("resting_hr", "").strip()) if r.get("resting_hr") is not None else None
        if hrv is None or sleep is None or rest is None:
            return None
        if hrv < hrv_threshold:
            reasons.append("hrv")
        if sleep < 7.0:
            reasons.append("sleep")
        if rest > rest_threshold:
            reasons.append("resting_hr")
        if reasons:
            flagged[date_str] = reasons
    return flagged


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "biometrics_csv_exists": 0.0,
        "biometrics_csv_structure": 0.0,
        "biometrics_csv_values": 0.0,
        "training_load_json_exists": 0.0,
        "training_load_json_values": 0.0,
        "flagged_days_csv_exists": 0.0,
        "flagged_days_dates": 0.0,
        "flagged_days_reasons": 0.0,
        "email_exists": 0.0,
        "email_subject_and_length": 0.0,
        "email_content_requirements": 0.0,
        "error_diagnosis_exists": 0.0,
        "error_diagnosis_content": 0.0,
    }

    # Compute expectations from inputs
    expected_bio = _compute_expected_biometrics(workspace)
    expected_load = _compute_expected_training_load(workspace)
    expected_flags = _compute_expected_flagged_days(workspace)

    # 1) Biometrics summary CSV
    bio_out = workspace / "out" / "biometrics_summary.csv"
    bio_rows, bio_fields = _read_csv_dicts(bio_out)
    if bio_rows is not None and bio_fields is not None:
        scores["biometrics_csv_exists"] = 1.0
        # Check structure: exact columns and metrics
        expected_fields = ["metric", "baseline_mean", "last7_mean", "pct_change"]
        if bio_fields == expected_fields:
            metrics_present = [r.get("metric") for r in bio_rows if r.get("metric") is not None]
            if set(metrics_present) == {"sleep_hours", "resting_hr", "hrv"} and len(bio_rows) == 3:
                scores["biometrics_csv_structure"] = 1.0
        # Check values
        if expected_bio is not None and bio_rows is not None:
            value_ok = True
            by_metric = {r.get("metric"): r for r in bio_rows if r.get("metric")}
            for m in ["sleep_hours", "resting_hr", "hrv"]:
                r = by_metric.get(m)
                if r is None:
                    value_ok = False
                    break
                b = _to_float(r.get("baseline_mean", ""))
                l7 = _to_float(r.get("last7_mean", ""))
                pct = _to_float(r.get("pct_change", ""))
                exp_b = expected_bio["baseline_means"][m]
                exp_l7 = expected_bio["last7_means"][m]
                exp_pct = expected_bio["pct_changes"][m]
                if not (_approx_equal(b, exp_b, abs_tol=0.05, rel_tol=1e-3)
                        and _approx_equal(l7, exp_l7, abs_tol=0.05, rel_tol=1e-3)
                        and _approx_equal(pct, exp_pct, abs_tol=0.1, rel_tol=1e-3)):
                    value_ok = False
                    break
            if value_ok:
                scores["biometrics_csv_values"] = 1.0

    # 2) Training load summary JSON
    load_out = workspace / "out" / "training_load_summary.json"
    load_json = _safe_load_json(load_out)
    if load_json is not None and isinstance(load_json, dict):
        scores["training_load_json_exists"] = 1.0
        if expected_load is not None:
            keys_required = ["acute_avg_load", "chronic_avg_load", "ratio", "acute_total_load", "chronic_total_load"]
            has_keys = all(k in load_json for k in keys_required)
            if has_keys:
                try:
                    aavg = float(load_json["acute_avg_load"])
                    cavg = float(load_json["chronic_avg_load"])
                    ratio = float(load_json["ratio"])
                    atot = float(load_json["acute_total_load"])
                    ctot = float(load_json["chronic_total_load"])
                    ok = True
                    ok &= _approx_equal(aavg, expected_load["acute_avg_load"], abs_tol=0.1, rel_tol=1e-3)
                    ok &= _approx_equal(cavg, expected_load["chronic_avg_load"], abs_tol=0.1, rel_tol=1e-3)
                    ok &= _approx_equal(ratio, expected_load["ratio"], abs_tol=1e-3, rel_tol=1e-3)
                    ok &= _approx_equal(atot, expected_load["acute_total_load"], abs_tol=0.1, rel_tol=1e-3)
                    ok &= _approx_equal(ctot, expected_load["chronic_total_load"], abs_tol=0.1, rel_tol=1e-3)
                    if ok:
                        scores["training_load_json_values"] = 1.0
                except Exception:
                    pass

    # 3) Flagged days CSV
    flags_out = workspace / "out" / "flagged_days.csv"
    flags_rows, flags_fields = _read_csv_dicts(flags_out)
    if flags_rows is not None and flags_fields is not None:
        scores["flagged_days_csv_exists"] = 1.0
        expected_fields = ["date", "reasons"]
        dates_ok = False
        reasons_ok = False
        if flags_fields == expected_fields and expected_bio is not None and expected_flags is not None:
            out_dates = []
            per_date_reasons = {}
            for r in flags_rows:
                date_str = r.get("date")
                reasons_str = r.get("reasons", "")
                if date_str is None:
                    continue
                out_dates.append(date_str)
                per_date_reasons[date_str] = reasons_str
            expected_dates = sorted(expected_flags.keys())
            if sorted(out_dates) == expected_dates:
                dates_ok = True

            all_ok = True
            for d, exp_reasons in expected_flags.items():
                text = per_date_reasons.get(d, "")
                parts = [p.strip().lower() for p in text.split(";") if p.strip()]
                found = set()
                for p in parts:
                    if "hrv" in p:
                        found.add("hrv")
                    if "sleep" in p:
                        found.add("sleep")
                    if "resting" in p or "rest" in p:
                        found.add("resting_hr")
                if not set(exp_reasons).issubset(found):
                    all_ok = False
                    break
            if all_ok:
                reasons_ok = True

        if dates_ok:
            scores["flagged_days_dates"] = 1.0
        if reasons_ok:
            scores["flagged_days_reasons"] = 1.0

    # 4) Email to trainer and coach
    email_path = workspace / "out" / "email_to_trainer.txt"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        scores["email_exists"] = 1.0
        lines = [ln for ln in email_text.splitlines()]
        first_non_blank = None
        for ln in lines:
            if ln.strip():
                first_non_blank = ln
                break
        subject_ok = bool(first_non_blank and first_non_blank.strip().lower().startswith("subject:"))
        words = [w for w in email_text.replace("\n", " ").split() if w.strip()]
        word_count = len(words)
        length_ok = 130 <= word_count <= 230
        if subject_ok and length_ok:
            scores["email_subject_and_length"] = 1.0

        text_lower = email_text.lower()
        audience_ok = ("coach" in text_lower) and ("trainer" in text_lower)
        biometrics_ok = ("sleep" in text_lower) and (("hrv" in text_lower) or ("heart rate variability" in text_lower)) and (("resting hr" in text_lower) or ("resting heart" in text_lower) or ("resting heart rate" in text_lower) or ("resting" in text_lower))
        ratio_ok = ("acute:chronic" in text_lower) or ("acute/chronic" in text_lower) or ("ratio" in text_lower)
        flagged_dates_ok = True
        if expected_flags is not None and expected_flags:
            for d in sorted(expected_flags.keys()):
                if d not in email_text:
                    flagged_dates_ok = False
                    break
        content_ok = audience_ok and biometrics_ok and ratio_ok and flagged_dates_ok
        if content_ok:
            scores["email_content_requirements"] = 1.0

    # 5) Error diagnosis
    err_path = workspace / "out" / "error_diagnosis.txt"
    err_text = _safe_read_text(err_path)
    if err_text is not None:
        scores["error_diagnosis_exists"] = 1.0
        tl = err_text.lower()
        cause_ok = ("modulenotfounderror" in tl) or ("no module named" in tl)
        pandas_ok = "pandas" in tl
        why_ok = ("import" in tl) and (("not installed" in tl) or ("missing" in tl))
        avoidance_ok = ("avoided" in tl) or ("manual" in tl) or ("without" in tl and "script" in tl) or ("standard library" in tl) or ("computed directly" in tl)
        if cause_ok and pandas_ok and why_ok and avoidance_ok:
            scores["error_diagnosis_content"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()