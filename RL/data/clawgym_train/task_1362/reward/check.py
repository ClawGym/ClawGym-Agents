import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _daterange(start_date, end_date):
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)


def _closish(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-2) -> bool:
    try:
        if a == b:
            return True
        if abs(a - b) <= abs_tol:
            return True
        if b != 0 and abs((a - b) / b) <= rel_tol:
            return True
        return False
    except Exception:
        return False


def _read_daily_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = ["date", "shift", "tonnes", "grade_gpt", "recovery_pct"]
            if reader.fieldnames is None or any(col not in reader.fieldnames for col in required):
                return None
            rows = []
            for r in reader:
                try:
                    rows.append({
                        "date": r["date"],
                        "shift": r["shift"],
                        "tonnes": float(r["tonnes"]),
                        "grade_gpt": float(r["grade_gpt"]),
                        "recovery_pct": float(r["recovery_pct"]),
                    })
                except Exception:
                    return None
            return rows
    except Exception:
        return None


def _compute_day_metrics(rows):
    # rows are for a single date across shifts
    tonnes_sum = sum(r["tonnes"] for r in rows)
    contained_sum = sum(r["tonnes"] * r["grade_gpt"] for r in rows)
    recovered_sum = sum(r["tonnes"] * r["grade_gpt"] * (r["recovery_pct"] / 100.0) for r in rows)
    weighted_grade = (contained_sum / tonnes_sum) if tonnes_sum != 0 else 0.0
    effective_recovery = (100.0 * (recovered_sum / contained_sum)) if contained_sum != 0 else 0.0
    return {
        "tonnes_day": tonnes_sum,
        "contained_gold_g": contained_sum,
        "recovered_gold_g": recovered_sum,
        "weighted_grade_gpt": weighted_grade,
        "effective_recovery_pct": effective_recovery,
    }


def _parse_bullet_lines(text: str):
    lines = text.splitlines()
    bullets = []
    for ln in lines:
        if re.match(r"^\s*[-*]\s+", ln):
            bullets.append(ln.strip())
    return bullets


def _count_sentences(paragraph: str) -> int:
    # naive sentence split by . ! ? followed by space or end
    parts = re.split(r"[.!?](?:\s|$)", paragraph.strip())
    # remove empty trailing parts
    parts = [p for p in parts if p.strip() != ""]
    return len(parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "inventory_lists_all_found_files": 0.0,
        "inventory_lists_all_missing_dates": 0.0,
        "weekly_metrics_exists_and_header": 0.0,
        "weekly_metrics_row_count_correct": 0.0,
        "weekly_metrics_daily_values_match": 0.0,
        "weekly_metrics_total_row_match": 0.0,
        "status_overview_paragraph_quality": 0.0,
        "status_projections_vs_targets_labels_correct": 0.0,
        "status_shift_alerts_listed": 0.0,
    }

    # Inputs and expected range
    # Use explicit task range
    start_date = _parse_date("2026-04-15")
    end_date = _parse_date("2026-04-19")
    date_list = [d.strftime("%Y-%m-%d") for d in _daterange(start_date, end_date)]

    # Discover available daily files within range
    prod_dir = workspace / "input" / "production"
    found_by_date = {}
    if prod_dir.exists() and prod_dir.is_dir():
        for p in prod_dir.glob("daily_*.csv"):
            # extract date
            m = re.match(r"daily_(\d{4}-\d{2}-\d{2})\.csv$", p.name)
            if not m:
                continue
            ds = m.group(1)
            if ds in date_list:
                found_by_date[ds] = p
    # Determine missing dates
    missing_dates = [d for d in date_list if d not in found_by_date]

    # Load daily CSVs and compute expected per-day metrics and shift alerts
    expected_day_metrics = {}
    all_shift_rows = []  # list of dicts with date, shift, grade, recovery for alerts
    for ds, path in found_by_date.items():
        rows = _read_daily_csv(path)
        if rows is None:
            # treat as unavailable for metrics; but still count as found for inventory checks
            continue
        # filter rows exactly for that date (though files should only contain that date)
        rows = [r for r in rows if r.get("date") == ds]
        if len(rows) == 0:
            continue
        expected_day_metrics[ds] = _compute_day_metrics(rows)
        # collect for alerts
        for r in rows:
            all_shift_rows.append({
                "date": r["date"],
                "shift": r["shift"],
                "grade_gpt": r["grade_gpt"],
                "recovery_pct": r["recovery_pct"],
            })

    # Compute total metrics over available days
    total_metrics = None
    if expected_day_metrics:
        sum_tonnes = sum(v["tonnes_day"] for v in expected_day_metrics.values())
        sum_contained = sum(v["contained_gold_g"] for v in expected_day_metrics.values())
        sum_recovered = sum(v["recovered_gold_g"] for v in expected_day_metrics.values())
        weighted_grade = (sum_contained / sum_tonnes) if sum_tonnes != 0 else 0.0
        effective_recovery = (100.0 * (sum_recovered / sum_contained)) if sum_contained != 0 else 0.0
        total_metrics = {
            "tonnes_day": sum_tonnes,
            "contained_gold_g": sum_contained,
            "recovered_gold_g": sum_recovered,
            "weighted_grade_gpt": weighted_grade,
            "effective_recovery_pct": effective_recovery,
        }

    # Load targets JSON for projections and alert thresholds
    targets_path = workspace / "input" / "targets" / "weekly_targets.json"
    targets_json = _safe_load_json(targets_path)
    weekly_tonnage_target = None
    weekly_recovered_target = None
    grade_range = None
    min_recovery_pct = None
    alert_deviation_pct = None
    if isinstance(targets_json, dict):
        try:
            t = targets_json.get("targets", {})
            weekly_tonnage_target = float(t.get("weekly_tonnage_target"))
            weekly_recovered_target = float(t.get("weekly_recovered_gold_g_target"))
            grade_range_val = t.get("grade_target_gpt_range", None)
            if isinstance(grade_range_val, list) and len(grade_range_val) == 2:
                grade_range = (float(grade_range_val[0]), float(grade_range_val[1]))
            min_recovery_pct = float(t.get("min_recovery_pct"))
            alert_deviation_pct = float(t.get("alert_deviation_pct"))
        except Exception:
            weekly_tonnage_target = None
            weekly_recovered_target = None
            grade_range = None
            min_recovery_pct = None
            alert_deviation_pct = None

    # Compute expected projections and statuses if possible
    expected_projection_status = None
    if total_metrics is not None and weekly_tonnage_target is not None and weekly_recovered_target is not None and alert_deviation_pct is not None:
        num_days = len(expected_day_metrics)
        if num_days > 0:
            avg_tonnes = total_metrics["tonnes_day"] / num_days
            avg_recovered = total_metrics["recovered_gold_g"] / num_days
            projected_tonnage_5d = avg_tonnes * 5.0
            projected_recovered_5d = avg_recovered * 5.0
            tonnage_threshold = weekly_tonnage_target * (1.0 - alert_deviation_pct / 100.0)
            recovered_threshold = weekly_recovered_target * (1.0 - alert_deviation_pct / 100.0)
            tonnage_status = "on track" if projected_tonnage_5d >= tonnage_threshold else "behind"
            recovered_status = "on track" if projected_recovered_5d >= recovered_threshold else "behind"
            expected_projection_status = {
                "tonnage": tonnage_status,
                "recovered": recovered_status,
            }

    # Compute expected shift alerts
    expected_alerts = []
    if grade_range is not None and min_recovery_pct is not None:
        for r in all_shift_rows:
            reasons = []
            if not (grade_range[0] <= r["grade_gpt"] <= grade_range[1]):
                reasons.append("grade")
            if r["recovery_pct"] < min_recovery_pct:
                reasons.append("recovery")
            if reasons:
                expected_alerts.append({
                    "date": r["date"],
                    "shift": r["shift"],
                    "reasons": reasons,
                })

    # Paths to deliverables
    weekly_metrics_path = workspace / "output" / "weekly" / "weekly_metrics_2026-04-15_to_2026-04-19.csv"
    inventory_path = workspace / "output" / "weekly" / "file_inventory.txt"
    status_md_path = workspace / "output" / "weekly" / "weekly_status_2026-04-15_to_2026-04-19.md"

    # Check inventory file for found files and missing dates
    inv_text = _safe_read_text(inventory_path)
    if inv_text:
        inv_lines = [ln.strip() for ln in inv_text.splitlines() if ln.strip() != ""]
        # Found files: require lines that include both relative file path and its date
        found_pairs = set()
        for ln in inv_lines:
            for ds, p in found_by_date.items():
                if ds in ln and str(p.as_posix()) in ln:
                    found_pairs.add((ds, str(p.as_posix())))
        if len(found_by_date) > 0:
            scores["inventory_lists_all_found_files"] = len(found_pairs) / len(found_by_date)
        else:
            # If no files in range are present, consider this check trivially satisfied
            scores["inventory_lists_all_found_files"] = 1.0

        # Missing dates: require each missing date string to appear somewhere in the file
        if len(missing_dates) > 0:
            missing_hits = sum(1 for d in missing_dates if d in inv_text)
            scores["inventory_lists_all_missing_dates"] = missing_hits / len(missing_dates)
        else:
            # If none missing, this is trivially satisfied
            scores["inventory_lists_all_missing_dates"] = 1.0
    else:
        scores["inventory_lists_all_found_files"] = 0.0
        scores["inventory_lists_all_missing_dates"] = 0.0

    # Check weekly metrics CSV
    weekly_metrics_exists = weekly_metrics_path.exists()
    per_day_match_fraction = 0.0
    row_count_ok = 0.0
    total_row_ok = 0.0
    if weekly_metrics_exists:
        try:
            with weekly_metrics_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                expected_header = ["date", "tonnes_day", "contained_gold_g", "recovered_gold_g", "weighted_grade_gpt", "effective_recovery_pct"]
                if reader.fieldnames == expected_header:
                    scores["weekly_metrics_exists_and_header"] = 1.0
                else:
                    scores["weekly_metrics_exists_and_header"] = 0.0

                rows = list(reader)
                # Count expected rows: one per available day + 1 TOTAL row
                expected_row_count = len(expected_day_metrics) + 1 if len(expected_day_metrics) > 0 else 1
                # Validate row count if we can
                if len(expected_day_metrics) >= 0:
                    # We accept files that include only total (if no days available)
                    row_count_ok = 1.0 if len(rows) == expected_row_count else 0.0
                    scores["weekly_metrics_row_count_correct"] = row_count_ok

                # Build index
                daily_rows = {}
                total_rows = []
                for r in rows:
                    if "date" not in r:
                        continue
                    if r["date"] == "TOTAL":
                        total_rows.append(r)
                    else:
                        daily_rows[r["date"]] = r

                # Per-day check
                day_hits = 0
                day_total = max(len(expected_day_metrics), 1)
                for ds, metrics in expected_day_metrics.items():
                    r = daily_rows.get(ds)
                    if r is None:
                        continue
                    try:
                        ok = (
                            _closish(float(r["tonnes_day"]), metrics["tonnes_day"]) and
                            _closish(float(r["contained_gold_g"]), metrics["contained_gold_g"]) and
                            _closish(float(r["recovered_gold_g"]), metrics["recovered_gold_g"]) and
                            _closish(float(r["weighted_grade_gpt"]), metrics["weighted_grade_gpt"]) and
                            _closish(float(r["effective_recovery_pct"]), metrics["effective_recovery_pct"])
                        )
                    except Exception:
                        ok = False
                    if ok:
                        day_hits += 1
                if len(expected_day_metrics) > 0:
                    per_day_match_fraction = day_hits / len(expected_day_metrics)
                else:
                    per_day_match_fraction = 1.0  # if no days available, trivially pass
                scores["weekly_metrics_daily_values_match"] = per_day_match_fraction

                # TOTAL row check: exactly one TOTAL row, numeric values match
                if len(total_rows) == 1 and total_metrics is not None:
                    r = total_rows[0]
                    try:
                        ok = (
                            _closish(float(r["tonnes_day"]), total_metrics["tonnes_day"]) and
                            _closish(float(r["contained_gold_g"]), total_metrics["contained_gold_g"]) and
                            _closish(float(r["recovered_gold_g"]), total_metrics["recovered_gold_g"]) and
                            _closish(float(r["weighted_grade_gpt"]), total_metrics["weighted_grade_gpt"]) and
                            _closish(float(r["effective_recovery_pct"]), total_metrics["effective_recovery_pct"])
                        )
                    except Exception:
                        ok = False
                    total_row_ok = 1.0 if ok else 0.0
                else:
                    total_row_ok = 0.0
                scores["weekly_metrics_total_row_match"] = total_row_ok
        except Exception:
            # Malformed CSV
            scores["weekly_metrics_exists_and_header"] = 0.0
            scores["weekly_metrics_row_count_correct"] = 0.0
            scores["weekly_metrics_daily_values_match"] = 0.0
            scores["weekly_metrics_total_row_match"] = 0.0
    else:
        scores["weekly_metrics_exists_and_header"] = 0.0
        scores["weekly_metrics_row_count_correct"] = 0.0
        scores["weekly_metrics_daily_values_match"] = 0.0
        scores["weekly_metrics_total_row_match"] = 0.0

    # Check status summary markdown
    status_text = _safe_read_text(status_md_path)
    if status_text:
        # Overview paragraph: 3–5 sentences
        # Identify paragraphs by blank lines
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", status_text) if p.strip()]
        overview_ok = 0.0
        for p in paragraphs:
            num_sent = _count_sentences(p)
            if 3 <= num_sent <= 5:
                # We accept the first that meets sentence count
                overview_ok = 1.0
                break
        scores["status_overview_paragraph_quality"] = overview_ok

        # Projections vs targets labels
        proj_score = 0.0
        if expected_projection_status is not None:
            bullets = _parse_bullet_lines(status_text)
            # Find bullet for tonnage and recovered (gold)
            tonnage_line = None
            recovered_line = None
            for b in bullets:
                lb = b.lower()
                if ("tonnage" in lb or "tonnes" in lb) and tonnage_line is None:
                    tonnage_line = lb
                if ("recovered" in lb and "gold" in lb) and recovered_line is None:
                    recovered_line = lb
            tonnage_ok = 0.0
            recovered_ok = 0.0
            if tonnage_line is not None and expected_projection_status["tonnage"] in tonnage_line:
                tonnage_ok = 0.5
            if recovered_line is not None and expected_projection_status["recovered"] in recovered_line:
                recovered_ok = 0.5
            proj_score = tonnage_ok + recovered_ok
        scores["status_projections_vs_targets_labels_correct"] = proj_score

        # Shift-level alerts listed
        alerts_score = 0.0
        if expected_alerts:
            bullets = _parse_bullet_lines(status_text)
            bullets_lc = [b.lower() for b in bullets]
            hits = 0
            for alert in expected_alerts:
                date_str = alert["date"]
                shift_str = alert["shift"].lower()
                reasons = alert["reasons"]  # contains "grade" and/or "recovery"
                found = False
                for b in bullets_lc:
                    if date_str in b and shift_str in b:
                        # Check reasons presence; be lenient but require reason keywords
                        reason_ok = True
                        for rname in reasons:
                            if rname == "recovery":
                                # require mention of recovery and a qualifier suggesting an issue
                                if ("recover" not in b) or not any(k in b for k in ["low", "below", "<", "under"]):
                                    reason_ok = False
                            elif rname == "grade":
                                # require mention of grade and out-of-range-ish wording
                                if ("grade" not in b) or not any(k in b for k in ["out", "outside", "range", "below", "above", "<", ">"]):
                                    reason_ok = False
                        if reason_ok:
                            found = True
                            break
                if found:
                    hits += 1
            alerts_score = hits / len(expected_alerts) if len(expected_alerts) > 0 else 1.0
        else:
            # If no expected alerts (e.g., thresholds missing), cannot validate
            alerts_score = 0.0
        scores["status_shift_alerts_listed"] = alerts_score

        # Additionally ensure missing days mentioned somewhere in status text
        # We'll incorporate this into the overview quality if not already considered; but we avoid changing that score.
        # As a stricter separate check was not defined, we keep overview_quality as is.
        # However, if missing days exist and not mentioned anywhere, slightly penalize projections score? We won't.
        # The rubric already checks inventory for missing dates.
    else:
        scores["status_overview_paragraph_quality"] = 0.0
        scores["status_projections_vs_targets_labels_correct"] = 0.0
        scores["status_shift_alerts_listed"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()