import json
import sys
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            row = next(reader, None)
            if row is None:
                return []
            return row
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _format_float_4(x: float) -> str:
    return f"{x:.4f}"


def _compute_expected_from_inputs(workspace: Path, target_date: str) -> Optional[dict]:
    # Load inputs
    input_dir = workspace / "input"
    files = {
        "districts": input_dir / "districts.csv",
        "historical_ignitions": input_dir / "historical_ignitions.csv",
        "fuel_moisture": input_dir / "fuel_moisture.csv",
        "wind": input_dir / "wind.csv",
        "access": input_dir / "access.csv",
    }
    datasets = {k: _read_csv_dicts(v) for k, v in files.items()}
    if any(datasets[k] is None for k in datasets):
        return None

    # Parse districts
    districts = []
    id_to_acres = {}
    id_to_name = {}
    for row in datasets["districts"]:
        try:
            did = row["district_id"]
            name = row["name"]
            acres = int(row["acres"])
        except Exception:
            return None
        districts.append(did)
        id_to_name[did] = name
        id_to_acres[did] = acres

    # Load metrics for the target date
    ignitions_by_id = {}
    for row in datasets["historical_ignitions"]:
        if row.get("date") == target_date:
            try:
                ignitions_by_id[row["district_id"]] = float(row["ignitions"])
            except Exception:
                return None

    fmi_by_id = {}
    for row in datasets["fuel_moisture"]:
        if row.get("date") == target_date:
            try:
                fmi_by_id[row["district_id"]] = float(row["fmi"])
            except Exception:
                return None

    wind_by_id = {}
    for row in datasets["wind"]:
        if row.get("date") == target_date:
            try:
                wind_by_id[row["district_id"]] = float(row["wind_speed_mps"])
            except Exception:
                return None

    access_by_id = {}
    for row in datasets["access"]:
        try:
            access_by_id[row["district_id"]] = float(row["open_roads_km"])
        except Exception:
            return None

    # Compute min/max for available values
    def _min_max(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
        if not values:
            return None, None
        return min(values), max(values)

    ign_list = [v for k, v in ignitions_by_id.items() if k in districts]
    fmi_list = [v for k, v in fmi_by_id.items() if k in districts]
    wind_list = [v for k, v in wind_by_id.items() if k in districts]
    access_list = [v for k, v in access_by_id.items() if k in districts]

    ign_min, ign_max = _min_max(ign_list)
    fmi_min, fmi_max = _min_max(fmi_list)
    wind_min, wind_max = _min_max(wind_list)
    acc_min, acc_max = _min_max(access_list)

    # Normalization helper
    def norm(value: Optional[float], mn: Optional[float], mx: Optional[float]) -> float:
        if value is None or mn is None or mx is None:
            return 0.0
        if mx == mn:
            return 0.0
        return (value - mn) / (mx - mn)

    # Compute risk scores per district
    results = []
    for did in districts:
        ign_val = ignitions_by_id.get(did)
        fmi_val = fmi_by_id.get(did)
        wind_val = wind_by_id.get(did)
        acc_val = access_by_id.get(did)

        ign_n = norm(ign_val, ign_min, ign_max)
        fmi_n = norm(fmi_val, fmi_min, fmi_max)
        wind_n = norm(wind_val, wind_min, wind_max)
        acc_n = norm(acc_val, acc_min, acc_max)

        risk = 0.4 * ign_n + 0.3 * (1 - fmi_n) + 0.2 * wind_n + 0.1 * (1 - acc_n)
        results.append({
            "district_id": did,
            "name": id_to_name.get(did, ""),
            "date": target_date,
            "risk_score_float": risk,
            "risk_score_str": _format_float_4(risk),
            "acres": id_to_acres.get(did, 0),
        })

    # Sort by risk_score desc, tie-break by acres desc
    results_sorted = sorted(results, key=lambda r: (-r["risk_score_float"], -r["acres"], r["district_id"]))
    # Assign rank 1..n
    for idx, r in enumerate(results_sorted, start=1):
        r["rank"] = idx

    # Stats for validation
    stats = {
        "ignitions": {"min": ign_min, "max": ign_max},
        "fmi": {"min": fmi_min, "max": fmi_max},
        "wind_speed_mps": {"min": wind_min, "max": wind_max},
        "open_roads_km": {"min": acc_min, "max": acc_max},
    }

    # Record counts
    record_counts = {
        "districts": {"loaded": len(datasets["districts"]), "used_for_target_date": len(districts)},
        "historical_ignitions": {
            "loaded": len(datasets["historical_ignitions"]),
            "used_for_target_date": len(ignitions_by_id),
        },
        "fuel_moisture": {
            "loaded": len(datasets["fuel_moisture"]),
            "used_for_target_date": len(fmi_by_id),
        },
        "wind": {
            "loaded": len(datasets["wind"]),
            "used_for_target_date": len(wind_by_id),
        },
        "access": {
            "loaded": len(datasets["access"]),
            "used_for_target_date": len(access_by_id),
        },
    }

    return {
        "results_sorted": results_sorted,
        "stats": stats,
        "record_counts": record_counts,
        "districts_order": [r["district_id"] for r in results_sorted],
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "priority_csv_exists_and_header": 0.0,
        "priority_csv_row_count": 0.0,
        "priority_csv_risk_scores_correct": 0.0,
        "priority_csv_risk_score_formatting": 0.0,
        "priority_csv_sort_and_rank_correct": 0.0,
        "priority_csv_date_values_correct": 0.0,
        "validation_json_structure": 0.0,
        "validation_json_input_checks_correct": 0.0,
        "validation_json_record_counts_correct": 0.0,
        "validation_json_stats_correct": 0.0,
        "validation_json_notes_present": 0.0,
        "architecture_json_structure": 0.0,
        "architecture_data_paths_correct": 0.0,
        "architecture_scoring_details_correct": 0.0,
        "architecture_artifacts_correct": 0.0,
        "run_command_references_scripts": 0.0,
        "scripts_dir_present": 0.0,
    }

    target_date = "2023-06-02"
    expected_headers = {
        "input/districts.csv": ["district_id", "name", "acres"],
        "input/historical_ignitions.csv": ["date", "district_id", "ignitions"],
        "input/fuel_moisture.csv": ["date", "district_id", "fmi"],
        "input/wind.csv": ["date", "district_id", "wind_speed_mps"],
        "input/access.csv": ["district_id", "open_roads_km"],
    }

    # Compute expected data from inputs
    expected = _compute_expected_from_inputs(workspace, target_date)

    # Validate patrol_priority.csv
    priority_path = workspace / "output" / "patrol_priority.csv"
    if priority_path.exists():
        header = _read_csv_header(priority_path)
        expected_header = ["district_id", "name", "date", "risk_score", "rank"]
        if header == expected_header:
            scores["priority_csv_exists_and_header"] = 1.0
        # Load rows
        rows = _read_csv_dicts(priority_path)
        if rows is not None:
            # Row count equals number of districts in input
            expected_row_count = 0
            if expected is not None:
                expected_row_count = len(expected["results_sorted"])
            else:
                # Fallback: try reading districts.csv
                districts_rows = _read_csv_dicts(workspace / "input" / "districts.csv")
                expected_row_count = len(districts_rows) if districts_rows is not None else 0
            if expected_row_count > 0 and len(rows) == expected_row_count:
                scores["priority_csv_row_count"] = 1.0

            # Check date column
            if len(rows) > 0 and all(r.get("date") == target_date for r in rows):
                scores["priority_csv_date_values_correct"] = 1.0

            # Check risk_score formatting and values and sort order/rank if expected is available
            if expected is not None and len(expected["results_sorted"]) == len(rows):
                # Map by district_id
                out_by_id = {r.get("district_id"): r for r in rows}
                # Formatting check and score values
                fmt_ok = True
                values_ok = True
                for exp in expected["results_sorted"]:
                    did = exp["district_id"]
                    out = out_by_id.get(did)
                    if out is None:
                        values_ok = False
                        fmt_ok = False
                        break
                    rs = out.get("risk_score", "")
                    # Check formatting exactly 4 decimals
                    if not re.fullmatch(r"-?\d+\.\d{4}", str(rs)):
                        fmt_ok = False
                    # Compare numeric equality to expected rounded string
                    if str(rs) != exp["risk_score_str"]:
                        values_ok = False
                if fmt_ok:
                    scores["priority_csv_risk_score_formatting"] = 1.0
                if values_ok:
                    scores["priority_csv_risk_scores_correct"] = 1.0

                # Check sort order and rank correctness
                # Expected order list by district_id
                expected_order = [r["district_id"] for r in expected["results_sorted"]]
                out_order = [r["district_id"] for r in rows]
                order_ok = (out_order == expected_order)
                # Check rank values correspond to position 1..n
                rank_ok = True
                if order_ok:
                    for idx, r in enumerate(rows, start=1):
                        try:
                            rank_val = int(r.get("rank", ""))
                        except Exception:
                            rank_ok = False
                            break
                        if rank_val != idx:
                            rank_ok = False
                            break
                else:
                    rank_ok = False
                if order_ok and rank_ok:
                    scores["priority_csv_sort_and_rank_correct"] = 1.0

    # Validate validation.json
    validation_path = workspace / "output" / "validation.json"
    validation = _load_json(validation_path)
    if isinstance(validation, dict):
        # Structure presence
        has_keys = all(k in validation for k in ["input_checks", "record_counts", "stats", "notes"])
        if has_keys and isinstance(validation.get("input_checks"), dict) and isinstance(validation.get("record_counts"), dict) and isinstance(validation.get("stats"), dict):
            scores["validation_json_structure"] = 1.0

        # input_checks correctness
        input_checks_ok = True
        ic = validation.get("input_checks")
        if isinstance(ic, dict):
            for path_str, headers in expected_headers.items():
                entry = ic.get(path_str)
                if not isinstance(entry, dict):
                    input_checks_ok = False
                    break
                exists_flag = entry.get("exists")
                headers_match = entry.get("headers_match")
                # Verify actual workspace state
                real_path = workspace / path_str
                real_exists = real_path.exists()
                real_header = _read_csv_header(real_path) if real_exists else None
                real_match = (real_header == headers) if real_header is not None else False
                if exists_flag is not real_exists or headers_match is not real_match:
                    input_checks_ok = False
                    break
        else:
            input_checks_ok = False
        if input_checks_ok:
            scores["validation_json_input_checks_correct"] = 1.0

        # record_counts correctness
        rec_counts_ok = False
        if expected is not None:
            rc = validation.get("record_counts")
            if isinstance(rc, dict):
                try:
                    # Expect specific datasets
                    datasets_expected = expected["record_counts"]
                    rec_counts_ok = True
                    for k in ["districts", "historical_ignitions", "fuel_moisture", "wind", "access"]:
                        ent = rc.get(k)
                        if not isinstance(ent, dict):
                            rec_counts_ok = False
                            break
                        if ent.get("loaded") != datasets_expected[k]["loaded"]:
                            rec_counts_ok = False
                            break
                        if ent.get("used_for_target_date") != datasets_expected[k]["used_for_target_date"]:
                            rec_counts_ok = False
                            break
                except Exception:
                    rec_counts_ok = False
        if rec_counts_ok:
            scores["validation_json_record_counts_correct"] = 1.0

        # stats correctness
        stats_ok = False
        if expected is not None:
            st = validation.get("stats")
            if isinstance(st, dict):
                stats_ok = True
                for metric in ["ignitions", "fmi", "wind_speed_mps", "open_roads_km"]:
                    m = st.get(metric)
                    if not isinstance(m, dict):
                        stats_ok = False
                        break
                    exp_min = expected["stats"][metric]["min"]
                    exp_max = expected["stats"][metric]["max"]
                    if m.get("min") != exp_min or m.get("max") != exp_max:
                        stats_ok = False
                        break
        if stats_ok:
            scores["validation_json_stats_correct"] = 1.0

        # notes presence: should indicate none missing if none were missing
        notes_ok = False
        notes = validation.get("notes", "")
        try:
            if isinstance(notes, str):
                s = notes.strip().lower()
                if any(keyword in s for keyword in ["none", "no missing", "n/a", "no issues"]):
                    notes_ok = True
            elif isinstance(notes, list):
                # If represented as a list of missing items, expect empty
                notes_ok = (len(notes) == 0)
            elif isinstance(notes, dict):
                # If structured, allow empty dict
                notes_ok = (len(notes) == 0)
        except Exception:
            notes_ok = False
        if notes_ok:
            scores["validation_json_notes_present"] = 1.0

    # Validate architecture.json
    arch_path = workspace / "output" / "architecture.json"
    arch = _load_json(arch_path)
    if isinstance(arch, dict):
        # Structure check
        core_keys_present = all(k in arch for k in ["components", "data_paths", "scoring", "run", "artifacts"])
        comp_valid = isinstance(arch.get("components"), list) and all(
            isinstance(c, dict) and all(k in c for k in ["name", "responsibilities", "inputs", "outputs"])
            for c in arch.get("components", [])
        )
        data_paths_valid = isinstance(arch.get("data_paths"), dict)
        scoring_valid = isinstance(arch.get("scoring"), dict)
        run_valid = isinstance(arch.get("run"), str) and len(arch.get("run")) > 0
        artifacts_valid = isinstance(arch.get("artifacts"), dict)
        if core_keys_present and comp_valid and data_paths_valid and scoring_valid and run_valid and artifacts_valid:
            scores["architecture_json_structure"] = 1.0

        # data_paths correctness
        dp_ok = False
        dp = arch.get("data_paths") if isinstance(arch.get("data_paths"), dict) else None
        if dp is not None:
            expected_dp = {
                "districts": "input/districts.csv",
                "historical_ignitions": "input/historical_ignitions.csv",
                "fuel_moisture": "input/fuel_moisture.csv",
                "wind": "input/wind.csv",
                "access": "input/access.csv",
            }
            dp_ok = all(dp.get(k) == v for k, v in expected_dp.items())
        if dp_ok:
            scores["architecture_data_paths_correct"] = 1.0

        # scoring details correctness
        scoring_ok = False
        scoring = arch.get("scoring") if isinstance(arch.get("scoring"), dict) else None
        if scoring is not None:
            td_ok = scoring.get("target_date") == "2023-06-02"
            weights = scoring.get("weights") if isinstance(scoring.get("weights"), dict) else None
            weights_ok = False
            if weights is not None:
                try:
                    weights_ok = (
                        float(weights.get("ignitions", "nan")) == 0.4 and
                        float(weights.get("fmi", "nan")) == 0.3 and
                        float(weights.get("wind", "nan")) == 0.2 and
                        float(weights.get("access", "nan")) == 0.1
                    )
                except Exception:
                    weights_ok = False
            normalization = scoring.get("normalization")
            norm_ok = False
            if isinstance(normalization, str):
                s = normalization.strip().lower().replace(" ", "")
                norm_ok = ("min-max" in s) or ("minmax" in s)
            formula = scoring.get("formula")
            formula_ok = False
            if isinstance(formula, str):
                fs = formula.lower()
                has_weights = all(str(w) in fs for w in [0.4, 0.3, 0.2, 0.1])
                has_invert_fmi = ("1-fmi" in fs) or ("1 - fmi" in fs) or ("(1-fmi" in fs) or ("(1 - fmi" in fs) or ("1-fmi_norm" in fs) or ("1 - fmi_norm" in fs)
                has_invert_access = ("1-access" in fs) or ("1 - access" in fs) or ("(1-access" in fs) or ("(1 - access" in fs) or ("1-access_norm" in fs) or ("1 - access_norm" in fs)
                mentions_ign = "ignit" in fs
                mentions_wind = "wind" in fs
                formula_ok = has_weights and has_invert_fmi and has_invert_access and mentions_ign and mentions_wind
            scoring_ok = td_ok and weights_ok and norm_ok and formula_ok
        if scoring_ok:
            scores["architecture_scoring_details_correct"] = 1.0

        # artifacts correctness
        artifacts_ok = False
        artifacts = arch.get("artifacts") if isinstance(arch.get("artifacts"), dict) else None
        if artifacts is not None:
            prio = artifacts.get("priority_csv")
            valj = artifacts.get("validation_json")
            artifacts_ok = (prio == "output/patrol_priority.csv" and valj == "output/validation.json")
            # Also ensure files exist
            artifacts_ok = artifacts_ok and (workspace / "output" / "patrol_priority.csv").exists() and (workspace / "output" / "validation.json").exists()
        if artifacts_ok:
            scores["architecture_artifacts_correct"] = 1.0

        # run command check for scripts
        run_ok = False
        run_cmd = arch.get("run")
        if isinstance(run_cmd, str):
            run_ok = ("scripts/" in run_cmd) and ("output/patrol_priority.csv" in run_cmd)
        if run_ok:
            scores["run_command_references_scripts"] = 1.0

    # scripts dir presence
    scripts_dir = workspace / "scripts"
    if scripts_dir.exists() and scripts_dir.is_dir():
        # any file or script present
        any_files = any(p.is_file() for p in scripts_dir.rglob("*"))
        if any_files:
            scores["scripts_dir_present"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()