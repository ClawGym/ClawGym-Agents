import sys
import json
import csv
from pathlib import Path
from datetime import datetime
from statistics import mean, median


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_pm25_input(csv_path: Path):
    if not csv_path.exists():
        return None
    records = []
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if 'date' not in reader.fieldnames or 'pm25' not in reader.fieldnames:
                return None
            for row in reader:
                try:
                    d = datetime.strptime(row['date'], '%Y-%m-%d').date()
                    v = float(row['pm25'])
                    records.append((d, v))
                except Exception:
                    # Skip malformed rows to mirror the analysis script behavior
                    continue
    except Exception:
        return None
    return records


def _group_by_month(records):
    buckets = {}
    for d, v in records:
        key = (d.year, d.month)
        buckets.setdefault(key, []).append(v)
    return buckets


def _group_by_year(records):
    buckets = {}
    for d, v in records:
        key = d.year
        buckets.setdefault(key, []).append(v)
    return buckets


def _summarize(values, threshold):
    if not values:
        return {
            'days': 0,
            'mean_pm25': None,
            'median_pm25': None,
            'min_pm25': None,
            'max_pm25': None,
            'days_exceeding_threshold': 0,
        }
    return {
        'days': len(values),
        'mean_pm25': round(mean(values), 3),
        'median_pm25': round(median(values), 3),
        'min_pm25': round(min(values), 3),
        'max_pm25': round(max(values), 3),
        'days_exceeding_threshold': sum(1 for x in values if x > threshold),
    }


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                return None, None
            rows = list(reader)
            return fieldnames, rows
    except Exception:
        return None, None


def _try_int(x):
    try:
        return int(x)
    except Exception:
        return None


def _try_float(x):
    try:
        return float(x)
    except Exception:
        return None


def _compare_float(a, b, places=3):
    if a is None or b is None:
        return False
    return round(float(a), places) == round(float(b), places)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "config_has_expected_keys": 0.0,
        "config_paths_match_requirements": 0.0,
        "outputs_present": 0.0,
        "monthly_header_valid": 0.0,
        "yearly_header_valid": 0.0,
        "monthly_sorted": 0.0,
        "monthly_aggregations_correct": 0.0,
        "yearly_aggregations_correct": 0.0,
        "run_log_has_success_markers": 0.0,
        "run_log_values_correct": 0.0,
    }

    # Load and validate config
    cfg_path = workspace / "config" / "analysis.json"
    cfg = _safe_load_json(cfg_path)
    if cfg is not None and isinstance(cfg, dict):
        has_input_csv = 'input_csv' in cfg
        has_output_dir = 'output_dir' in cfg
        if has_input_csv and has_output_dir:
            scores["config_has_expected_keys"] = 1.0

        # Strict path checks per task
        if has_input_csv and has_output_dir:
            input_csv_val = str(cfg.get('input_csv'))
            output_dir_val = str(cfg.get('output_dir'))
            if input_csv_val == "data/newham_pm25_2005_2006.csv" and output_dir_val == "output":
                scores["config_paths_match_requirements"] = 1.0

    # Expected deliverable output paths
    out_dir = workspace / "output"
    monthly_out = out_dir / "monthly_summary.csv"
    yearly_out = out_dir / "yearly_summary.csv"
    run_log = out_dir / "run.log"

    # Outputs presence
    if monthly_out.exists() and yearly_out.exists() and run_log.exists():
        scores["outputs_present"] = 1.0

    # Expected input paths and data
    expected_input_csv = workspace / "data" / "newham_pm25_2005_2006.csv"
    records = _read_pm25_input(expected_input_csv)
    # Determine threshold from config if present, else default (as script does)
    threshold = None
    if cfg is not None and isinstance(cfg, dict) and 'exceedance_threshold' in cfg:
        try:
            threshold = float(cfg['exceedance_threshold'])
        except Exception:
            threshold = None
    if threshold is None:
        threshold = 25.0

    # Compute expected groupings and summaries if possible
    expected_monthly = None
    expected_yearly = None
    if records is not None and len(records) > 0:
        monthly_groups = _group_by_month(records)
        yearly_groups = _group_by_year(records)
        expected_monthly = {}
        for key in monthly_groups:
            expected_monthly[key] = _summarize(monthly_groups[key], threshold)
        expected_yearly = {}
        for key in yearly_groups:
            expected_yearly[key] = _summarize(yearly_groups[key], threshold)

    # Validate monthly header structure
    exp_monthly_fields = [
        'year', 'month', 'days', 'mean_pm25', 'median_pm25', 'min_pm25', 'max_pm25', 'days_exceeding_threshold'
    ]
    m_fields, m_rows = _load_csv_dicts(monthly_out) if monthly_out.exists() else (None, None)
    if m_fields is not None and m_fields == exp_monthly_fields:
        scores["monthly_header_valid"] = 1.0

    # Validate yearly header structure
    exp_yearly_fields = [
        'year', 'days', 'mean_pm25', 'median_pm25', 'min_pm25', 'max_pm25', 'days_exceeding_threshold'
    ]
    y_fields, y_rows = _load_csv_dicts(yearly_out) if yearly_out.exists() else (None, None)
    if y_fields is not None and y_fields == exp_yearly_fields:
        scores["yearly_header_valid"] = 1.0

    # Check monthly content correctness and sorting
    if m_fields is not None and m_rows is not None and expected_monthly is not None:
        # Check sorting
        try:
            keys_in_file = []
            for row in m_rows:
                y = _try_int(row.get('year'))
                mo = _try_int(row.get('month'))
                keys_in_file.append((y, mo))
            if all(k[0] is not None and k[1] is not None for k in keys_in_file):
                if keys_in_file == sorted(keys_in_file):
                    scores["monthly_sorted"] = 1.0
        except Exception:
            pass

        # Check content match
        try:
            # Build map of file rows
            file_map = {}
            for row in m_rows:
                y = _try_int(row.get('year'))
                mo = _try_int(row.get('month'))
                if y is None or mo is None:
                    file_map = None
                    break
                # Parse numeric fields
                days = _try_int(row.get('days'))
                mean_v = _try_float(row.get('mean_pm25'))
                median_v = _try_float(row.get('median_pm25'))
                min_v = _try_float(row.get('min_pm25'))
                max_v = _try_float(row.get('max_pm25'))
                days_exc = _try_int(row.get('days_exceeding_threshold'))
                file_map[(y, mo)] = {
                    'days': days,
                    'mean_pm25': mean_v,
                    'median_pm25': median_v,
                    'min_pm25': min_v,
                    'max_pm25': max_v,
                    'days_exceeding_threshold': days_exc
                }
            if file_map is not None:
                # Compare set of keys
                if set(file_map.keys()) == set(expected_monthly.keys()):
                    ok = True
                    for key in expected_monthly:
                        exp = expected_monthly[key]
                        got = file_map[key]
                        if got['days'] != exp['days']:
                            ok = False
                            break
                        if not _compare_float(got['mean_pm25'], exp['mean_pm25'], 3):
                            ok = False
                            break
                        if not _compare_float(got['median_pm25'], exp['median_pm25'], 3):
                            ok = False
                            break
                        if not _compare_float(got['min_pm25'], exp['min_pm25'], 3):
                            ok = False
                            break
                        if not _compare_float(got['max_pm25'], exp['max_pm25'], 3):
                            ok = False
                            break
                        if got['days_exceeding_threshold'] != exp['days_exceeding_threshold']:
                            ok = False
                            break
                    if ok:
                        scores["monthly_aggregations_correct"] = 1.0
        except Exception:
            pass

    # Check yearly content correctness
    if y_fields is not None and y_rows is not None and expected_yearly is not None:
        try:
            file_map_y = {}
            for row in y_rows:
                y = _try_int(row.get('year'))
                if y is None:
                    file_map_y = None
                    break
                days = _try_int(row.get('days'))
                mean_v = _try_float(row.get('mean_pm25'))
                median_v = _try_float(row.get('median_pm25'))
                min_v = _try_float(row.get('min_pm25'))
                max_v = _try_float(row.get('max_pm25'))
                days_exc = _try_int(row.get('days_exceeding_threshold'))
                file_map_y[y] = {
                    'days': days,
                    'mean_pm25': mean_v,
                    'median_pm25': median_v,
                    'min_pm25': min_v,
                    'max_pm25': max_v,
                    'days_exceeding_threshold': days_exc
                }
            if file_map_y is not None:
                if set(file_map_y.keys()) == set(expected_yearly.keys()):
                    oky = True
                    for key in expected_yearly:
                        exp = expected_yearly[key]
                        got = file_map_y[key]
                        if got['days'] != exp['days']:
                            oky = False
                            break
                        if not _compare_float(got['mean_pm25'], exp['mean_pm25'], 3):
                            oky = False
                            break
                        if not _compare_float(got['median_pm25'], exp['median_pm25'], 3):
                            oky = False
                            break
                        if not _compare_float(got['min_pm25'], exp['min_pm25'], 3):
                            oky = False
                            break
                        if not _compare_float(got['max_pm25'], exp['max_pm25'], 3):
                            oky = False
                            break
                        if got['days_exceeding_threshold'] != exp['days_exceeding_threshold']:
                            oky = False
                            break
                    if oky:
                        scores["yearly_aggregations_correct"] = 1.0
        except Exception:
            pass

    # Run log checks
    log_text = _safe_read_text(run_log) if run_log.exists() else None
    if log_text is not None:
        # Check presence of success markers
        markers_ok = True
        # Expected output dir is strictly "output" per task deliverable locations
        if "Wrote monthly summary to output/monthly_summary.csv" not in log_text:
            markers_ok = False
        if "Wrote yearly summary to output/yearly_summary.csv" not in log_text:
            markers_ok = False
        if "Processed " not in log_text:
            markers_ok = False
        if "Threshold for exceedance: " not in log_text:
            markers_ok = False
        if markers_ok:
            scores["run_log_has_success_markers"] = 1.0

        # Check values in log (counts and threshold)
        if records is not None and expected_monthly is not None and expected_yearly is not None:
            total_readings = len(records)
            months_count = len(expected_monthly)
            years_count = len(expected_yearly)
            expected_line = f"Processed {total_readings} total readings across {months_count} months and {years_count} years."
            thr_line = f"Threshold for exceedance: {threshold}"
            values_ok = True
            if expected_line not in log_text:
                values_ok = False
            if thr_line not in log_text:
                values_ok = False
            if values_ok:
                scores["run_log_values_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()