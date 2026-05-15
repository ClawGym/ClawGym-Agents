import json
import os
import sys
import csv
import math

def is_finite_number(x):
    return isinstance(x, (int, float)) and math.isfinite(float(x))

def validate_matrix_3x3(M):
    if not isinstance(M, list) or len(M) != 3:
        return False
    for row in M:
        if not isinstance(row, list) or len(row) != 3:
            return False
        for v in row:
            if not is_finite_number(v):
                return False
    return True

def validate_vector_3(v):
    if not isinstance(v, list) or len(v) != 3:
        return False
    for x in v:
        if not is_finite_number(x):
            return False
    return True

def mat_vec_mul(M, v):
    # M: 3x3, v: 3
    return [
        M[0][0]*v[0] + M[0][1]*v[1] + M[0][2]*v[2],
        M[1][0]*v[0] + M[1][1]*v[1] + M[1][2]*v[2],
        M[2][0]*v[0] + M[2][1]*v[1] + M[2][2]*v[2],
    ]

def vec_sub(a, b):
    return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]

def norm3(v):
    return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])

def mean_std(vals):
    n = len(vals)
    if n == 0:
        return (float('nan'), float('nan'))
    m = sum(vals) / n
    var = sum((x - m) ** 2 for x in vals) / n
    return (m, math.sqrt(var))

def fraction_within(vals, lo, hi):
    n = len(vals)
    if n == 0:
        return float('nan')
    count = sum(1 for x in vals if (x >= lo and x <= hi))
    return count / n

def median(vals):
    n = len(vals)
    if n == 0:
        return float('nan')
    s = sorted(vals)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    else:
        return (s[mid-1] + s[mid]) / 2.0

def read_input_mags(input_csv_path):
    if not os.path.isfile(input_csv_path):
        return []
    mags = []
    with open(input_csv_path, "r", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return []
        # Normalize header by stripping spaces
        header = [h.strip() for h in header]
        try:
            ix_mx = header.index("mx")
            ix_my = header.index("my")
            ix_mz = header.index("mz")
        except ValueError:
            return []
        for row in reader:
            if len(row) <= max(ix_mx, ix_my, ix_mz):
                continue
            try:
                mx = float(row[ix_mx])
                my = float(row[ix_my])
                mz = float(row[ix_mz])
                if math.isfinite(mx) and math.isfinite(my) and math.isfinite(mz):
                    mags.append([mx, my, mz])
            except Exception:
                # Skip rows that cannot be parsed to floats
                continue
    return mags

def close_enough(reported, recomputed, abs_tol=0.05, rel_tol=0.10):
    if not (is_finite_number(reported) and is_finite_number(recomputed)):
        return False
    diff = abs(float(reported) - float(recomputed))
    scale = max(abs(float(recomputed)), 1e-12)
    allowed = max(abs_tol, rel_tol * scale)
    return diff <= allowed

def read_json_file(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return None

def parse_calibrated_csv(path):
    if not os.path.isfile(path):
        return None, None
    with open(path, "r", newline="") as f:
        # Read raw first line to check exact header
        first_line = f.readline()
        if first_line is None:
            return False, []
        raw_header = first_line.strip()
        header_ok = (raw_header == "mx,my,mz")
        # Now read remaining lines as csv to parse numeric values
        f.seek(0)
        reader = csv.reader(f)
        header_list = next(reader, None)
        rows = []
        for row in reader:
            if len(row) != 3:
                return header_ok, []  # invalid row width
            try:
                mx = float(row[0])
                my = float(row[1])
                mz = float(row[2])
                if not (math.isfinite(mx) and math.isfinite(my) and math.isfinite(mz)):
                    return header_ok, []
                rows.append([mx, my, mz])
            except Exception:
                return header_ok, []
        return header_ok, rows

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_calibration_json": False,
        "calibration_json_parsed": False,
        "calibration_shape_correct": False,
        "calibration_numeric_finite": False,

        "has_calibrated_mags_csv": False,
        "calibrated_mags_header_ok": False,
        "calibrated_mags_row_count_200": False,
        "calibrated_mags_matches_parameters": False,

        "has_metrics_json": False,
        "metrics_json_parsed": False,
        "metrics_keys_present": False,
        "metrics_values_numeric_finite": False,
        "metrics_match_recomputed": False,

        "sphericity_improved_std": False,
        "sphericity_cal_std_threshold": False,
        "sphericity_fraction_after_threshold": False,
        "sphericity_mean_or_median_in_range": False,

        "has_report_md": False,
        "report_contains_required_terms": False,

        "has_readme_md": False,
        "readme_mentions_paths": False,
    }

    # Paths
    input_csv_path = os.path.join(input_dir, "imu_session.csv")
    calibration_json_path = os.path.join(output_dir, "calibration.json")
    calibrated_csv_path = os.path.join(output_dir, "calibrated_mags.csv")
    metrics_json_path = os.path.join(output_dir, "metrics.json")
    report_md_path = os.path.join(output_dir, "report.md")
    readme_md_path = os.path.join(output_dir, "README.md")

    # Load input mags
    raw_mags = read_input_mags(input_csv_path)

    # 1) Calibration JSON
    Sm = None
    h = None
    if os.path.isfile(calibration_json_path):
        checks["has_calibration_json"] = True
        cal_json = read_json_file(calibration_json_path)
        if cal_json is not None and isinstance(cal_json, dict):
            checks["calibration_json_parsed"] = True
            if "Sm" in cal_json and "h" in cal_json:
                M = cal_json.get("Sm")
                v = cal_json.get("h")
                shape_ok = validate_matrix_3x3(M) and validate_vector_3(v)
                checks["calibration_shape_correct"] = shape_ok
                if shape_ok:
                    # ensure numeric/finiteness confirmed
                    all_nums = all(is_finite_number(M[i][j]) for i in range(3) for j in range(3)) and all(is_finite_number(x) for x in v)
                    checks["calibration_numeric_finite"] = all_nums
                    if all_nums:
                        # convert to floats
                        Sm = [[float(M[i][j]) for j in range(3)] for i in range(3)]
                        h = [float(x) for x in v]

    # 2) Calibrated mags CSV
    header_ok = None
    cal_rows = None
    if os.path.isfile(calibrated_csv_path):
        checks["has_calibrated_mags_csv"] = True
        header_ok, cal_rows = parse_calibrated_csv(calibrated_csv_path)
        if isinstance(header_ok, bool):
            checks["calibrated_mags_header_ok"] = header_ok
        if isinstance(cal_rows, list):
            checks["calibrated_mags_row_count_200"] = (len(cal_rows) == 200)
        # Compare with recomputed based on first 200 raw mags
        if checks["calibrated_mags_row_count_200"] and checks["calibration_numeric_finite"] and raw_mags and len(raw_mags) >= 200:
            ok = True
            for i in range(200):
                raw_v = raw_mags[i]
                diff_v = vec_sub(raw_v, h)
                cal_v = mat_vec_mul(Sm, diff_v)
                reported_v = cal_rows[i]
                # Compare per component within abs tol 1e-3
                for k in range(3):
                    if abs(cal_v[k] - reported_v[k]) > 1e-3:
                        ok = False
                        break
                if not ok:
                    break
            checks["calibrated_mags_matches_parameters"] = ok

    # 3) Metrics JSON and recomputation
    recomputed_metrics = None
    if os.path.isfile(metrics_json_path):
        checks["has_metrics_json"] = True
        met_json = read_json_file(metrics_json_path)
        if met_json is not None and isinstance(met_json, dict):
            checks["metrics_json_parsed"] = True
            required_keys = [
                "raw_norm_mean", "raw_norm_std",
                "cal_norm_mean", "cal_norm_std",
                "frac_within_0p9_1p1_before", "frac_within_0p9_1p1_after",
            ]
            keys_present = all(k in met_json for k in required_keys)
            checks["metrics_keys_present"] = keys_present
            if keys_present:
                # Validate numeric finiteness
                numeric_ok = all(is_finite_number(met_json[k]) for k in required_keys)
                checks["metrics_values_numeric_finite"] = numeric_ok

    # Recompute metrics using calibration and input mags
    raw_norms = []
    cal_norms = []
    if raw_mags and checks["calibration_numeric_finite"]:
        raw_norms = [norm3(v) for v in raw_mags]
        cal_norms = []
        for v in raw_mags:
            dv = vec_sub(v, h)
            cv = mat_vec_mul(Sm, dv)
            cal_norms.append(norm3(cv))

        raw_mean, raw_std = mean_std(raw_norms)
        cal_mean, cal_std = mean_std(cal_norms)
        frac_before = fraction_within(raw_norms, 0.9, 1.1)
        frac_after = fraction_within(cal_norms, 0.9, 1.1)

        recomputed_metrics = {
            "raw_norm_mean": raw_mean,
            "raw_norm_std": raw_std,
            "cal_norm_mean": cal_mean,
            "cal_norm_std": cal_std,
            "frac_within_0p9_1p1_before": frac_before,
            "frac_within_0p9_1p1_after": frac_after,
        }

        # Compare metrics when metrics.json present and parsed
        if checks["metrics_values_numeric_finite"]:
            met_json = read_json_file(metrics_json_path)
            if met_json is not None:
                all_match = True
                for k, rec_val in recomputed_metrics.items():
                    rep_val = met_json.get(k)
                    if not close_enough(rep_val, rec_val, abs_tol=0.05, rel_tol=0.10):
                        all_match = False
                        break
                checks["metrics_match_recomputed"] = all_match

        # 4) Sphericity improvement checks
        if is_finite_number(raw_std) and is_finite_number(cal_std):
            checks["sphericity_improved_std"] = (cal_std < raw_std)
            checks["sphericity_cal_std_threshold"] = (cal_std <= 0.15)
        if is_finite_number(frac_after):
            checks["sphericity_fraction_after_threshold"] = (frac_after >= 0.60)
        cal_med = median(cal_norms)
        mean_in_range = (is_finite_number(cal_mean) and cal_mean >= 0.8 and cal_mean <= 1.2)
        med_in_range = (is_finite_number(cal_med) and cal_med >= 0.8 and cal_med <= 1.2)
        checks["sphericity_mean_or_median_in_range"] = (mean_in_range or med_in_range)

    # 5) Report presence and required content
    if os.path.isfile(report_md_path):
        checks["has_report_md"] = True
        content = read_text_file(report_md_path) or ""
        # Required substrings
        required_subs = ["soft-iron", "hard-iron", "Sm @ (m_raw - h)", "assumption"]
        if all(sub in content for sub in required_subs):
            checks["report_contains_required_terms"] = True

    # 6) README presence and required mentions
    if os.path.isfile(readme_md_path):
        checks["has_readme_md"] = True
        readme_text = read_text_file(readme_md_path) or ""
        required_paths = [
            "input/imu_session.csv",
            "output/calibration.json",
            "output/metrics.json",
            "output/calibrated_mags.csv",
        ]
        if all(p in readme_text for p in required_paths):
            checks["readme_mentions_paths"] = True

    # Compute reward: proportion of passed checks; ensure baseline 0.0 when no outputs
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if (total_checks > 0 and passed_checks > 0) else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()