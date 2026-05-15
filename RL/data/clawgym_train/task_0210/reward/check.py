import json
import csv
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_safe(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            return rows
    except Exception:
        return None


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    if v == "":
        return ""
    # Remove surrounding quotes if present
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    # Try int
    try:
        iv = int(v)
        return iv
    except ValueError:
        pass
    # Try float
    try:
        fv = float(v)
        return fv
    except ValueError:
        pass
    # Return as string
    return v


def _load_simple_yaml_safe(path: Path) -> Optional[Dict[str, Any]]:
    # Minimal YAML loader for simple key: value and nested dictionaries via indentation
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in lines:
        if not raw_line.strip():
            continue
        # ignore full-line comments
        stripped = raw_line.split("#", 1)[0]
        if stripped.strip() == "":
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        line = stripped.strip()
        if ":" not in line:
            # Not supported structure
            return None
        key, rest = line.split(":", 1)
        key = key.strip()
        value_part = rest.strip()
        # Adjust stack based on indentation
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            # malformed indentation
            return None
        current_dict = stack[-1][1]
        if value_part == "":
            # Start new nested dict
            if key in current_dict and not isinstance(current_dict[key], dict):
                return None
            new_dict: Dict[str, Any] = {}
            current_dict[key] = new_dict
            stack.append((indent, new_dict))
        else:
            # Scalar value
            current_dict[key] = _parse_scalar(value_part)
    return root


def _float_close(a: float, b: float, tol: float) -> bool:
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    # Load required inputs
    panel_csv_path = workspace / "input" / "panel_tests.csv"
    assumptions_yaml_path = workspace / "input" / "assumptions.yaml"
    site_profile_yaml_path = workspace / "input" / "site_profile.yaml"

    panel_rows = _load_csv_safe(panel_csv_path)
    assumptions = _load_simple_yaml_safe(assumptions_yaml_path)
    site_profile = _load_simple_yaml_safe(site_profile_yaml_path)

    if panel_rows is None or assumptions is None or site_profile is None:
        return None

    # Validate assumptions structure
    try:
        temp_coeffs = assumptions["temperature_coefficients"]
        module_cost = assumptions["module_cost_usd"]
        performance_ratio = float(assumptions["performance_ratio"])
        tc_baseline = float(temp_coeffs["baseline"])
        tc_prototype = float(temp_coeffs["prototype"])
        cost_baseline = float(module_cost["baseline"])
        cost_prototype = float(module_cost["prototype"])
    except Exception:
        return None

    # Site profile fields
    try:
        avg_daily_insolation = float(site_profile["average_daily_insolation_kWh_per_m2"])
        electricity_price = float(site_profile["electricity_price_usd_per_kWh"])
        planned_modules = int(site_profile["planned_module_count"])
    except Exception:
        return None

    # Prepare mapping of tc by design
    tc_by_design = {
        "baseline": tc_baseline,
        "prototype": tc_prototype,
    }
    cost_by_design = {
        "baseline": cost_baseline,
        "prototype": cost_prototype,
    }

    # Compute per-test normalization
    per_test = []
    for row in panel_rows:
        try:
            test_id = row["test_id"].strip()
            design = row["design"].strip()
            irradiance = float(row["irradiance_W_m2"])
            temperature = float(row["temperature_C"])
            power_W = float(row["power_W"])
            area_m2 = float(row["area_m2"])
        except Exception:
            return None
        if design not in tc_by_design:
            return None
        tc = tc_by_design[design]
        denom = 1.0 + tc * (temperature - 25.0)
        # Avoid division by zero; if denom is zero, treat as failure
        if denom == 0.0:
            return None
        p_25c = power_W / denom
        if irradiance == 0.0:
            return None
        p_stc = p_25c * (1000.0 / irradiance)
        stc_eff = p_stc / (1000.0 * area_m2)
        per_test.append({
            "test_id": test_id,
            "design": design,
            "stc_power_W": p_stc,
            "stc_efficiency": stc_eff,
            "area_m2": area_m2,
        })

    # Aggregate per design
    by_design: Dict[str, List[Dict[str, Any]]] = {"baseline": [], "prototype": []}
    for r in per_test:
        by_design[r["design"]].append(r)

    def _avg(values: List[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    designs_metrics: Dict[str, Dict[str, Any]] = {}
    for design in ["baseline", "prototype"]:
        tests = by_design.get(design, [])
        if not tests:
            return None
        mean_eff = _avg([t["stc_efficiency"] for t in tests])
        mean_p_stc = _avg([t["stc_power_W"] for t in tests])
        mean_area = _avg([t["area_m2"] for t in tests])
        cpw = cost_by_design[design] / mean_p_stc
        annual_energy = planned_modules * mean_area * avg_daily_insolation * 365.0 * performance_ratio * mean_eff
        upfront_cost = planned_modules * cost_by_design[design]
        annual_savings = annual_energy * electricity_price
        payback_years = (upfront_cost / annual_savings) if annual_savings != 0 else float('inf')
        designs_metrics[design] = {
            "mean_stc_efficiency": mean_eff,
            "stc_power_W": mean_p_stc,
            "cost_per_watt_usd": cpw,
            "mean_area_m2": mean_area,
            "annual_energy_kWh": annual_energy,
            "annual_savings_usd": annual_savings,
            "upfront_cost_usd": upfront_cost,
            "payback_years": payback_years,
            "num_tests": len(tests),
        }

    # Top-level comparison metrics
    eff_gain_pct = (designs_metrics["prototype"]["mean_stc_efficiency"] / designs_metrics["baseline"]["mean_stc_efficiency"] - 1.0) * 100.0
    payback_improve_years = designs_metrics["baseline"]["payback_years"] - designs_metrics["prototype"]["payback_years"]

    expected = {
        "per_test": per_test,
        "designs": designs_metrics,
        "prototype_vs_baseline": {
            "efficiency_gain_pct": eff_gain_pct,
            "payback_improvement_years": payback_improve_years,
        },
        "assumptions": {
            "performance_ratio": performance_ratio,
            "average_daily_insolation_kWh_per_m2": avg_daily_insolation,
            "electricity_price_usd_per_kWh": electricity_price,
            "planned_module_count": planned_modules,
        },
    }
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "normalized_file_exists_and_header": 0.0,
        "normalized_rows_coverage": 0.0,
        "normalized_values_accuracy": 0.0,
        "metrics_file_structure_valid": 0.0,
        "metrics_designs_values_accuracy": 0.0,
        "metrics_prototype_vs_baseline_accuracy": 0.0,
        "metrics_assumptions_section_correct": 0.0,
        "metrics_num_tests_correct": 0.0,
        "email_recipient_and_references_present": 0.0,
        "email_numbers_present": 0.0,
        "email_subject_mentions_findings": 0.0,
    }

    expected = _compute_expected(workspace)
    # Paths to outputs
    out_norm_path = workspace / "output" / "normalized_per_test.csv"
    out_metrics_path = workspace / "output" / "metrics.json"
    out_email_path = workspace / "output" / "email_to_engineering.txt"

    # Check normalized_per_test.csv
    norm_rows = _load_csv_safe(out_norm_path)
    if norm_rows is not None:
        # Header check
        try:
            with out_norm_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        required_header = ["test_id", "design", "stc_power_W", "stc_efficiency", "area_m2"]
        if header == required_header:
            scores["normalized_file_exists_and_header"] = 1.0
        else:
            scores["normalized_file_exists_and_header"] = 0.0

        # Coverage and accuracy checks require expected data
        if expected is not None:
            expected_tests = {r["test_id"]: r for r in expected["per_test"]}
            # Coverage: all expected tests present and no duplicates
            try:
                present_ids = [r["test_id"].strip() for r in norm_rows]
                if set(present_ids) == set(expected_tests.keys()) and len(present_ids) == len(expected_tests):
                    scores["normalized_rows_coverage"] = 1.0
                else:
                    scores["normalized_rows_coverage"] = 0.0
            except Exception:
                scores["normalized_rows_coverage"] = 0.0

            # Values accuracy
            all_ok = True
            # Tolerances
            tol_power = 0.01
            tol_eff = 0.001
            tol_area = 0.005
            try:
                for r in norm_rows:
                    tid = r.get("test_id", "").strip()
                    design = r.get("design", "").strip()
                    if tid not in expected_tests:
                        all_ok = False
                        break
                    exp = expected_tests[tid]
                    if design != exp["design"]:
                        all_ok = False
                        break
                    try:
                        stc_power = float(r["stc_power_W"])
                        stc_eff = float(r["stc_efficiency"])
                        area = float(r["area_m2"])
                    except Exception:
                        all_ok = False
                        break
                    if not _float_close(stc_power, exp["stc_power_W"], tol_power):
                        all_ok = False
                        break
                    if not _float_close(stc_eff, exp["stc_efficiency"], tol_eff):
                        all_ok = False
                        break
                    if not _float_close(area, exp["area_m2"], tol_area):
                        all_ok = False
                        break
                scores["normalized_values_accuracy"] = 1.0 if all_ok else 0.0
            except Exception:
                scores["normalized_values_accuracy"] = 0.0
        else:
            scores["normalized_rows_coverage"] = 0.0
            scores["normalized_values_accuracy"] = 0.0
    else:
        scores["normalized_file_exists_and_header"] = 0.0
        scores["normalized_rows_coverage"] = 0.0
        scores["normalized_values_accuracy"] = 0.0

    # Check metrics.json
    metrics = _load_json_safe(out_metrics_path)
    if metrics is not None:
        # basic structure
        structure_ok = isinstance(metrics, dict) and \
                       "designs" in metrics and \
                       "prototype_vs_baseline" in metrics and \
                       "assumptions" in metrics and \
                       isinstance(metrics["designs"], dict) and \
                       "baseline" in metrics["designs"] and \
                       "prototype" in metrics["designs"]
        scores["metrics_file_structure_valid"] = 1.0 if structure_ok else 0.0

        if expected is not None and structure_ok:
            # Assumptions section correctness
            assumptions_ok = True
            try:
                ass = metrics["assumptions"]
                exp_ass = expected["assumptions"]
                if not _float_close(float(ass["performance_ratio"]), float(exp_ass["performance_ratio"]), 1e-9):
                    assumptions_ok = False
                if not _float_close(float(ass["average_daily_insolation_kWh_per_m2"]), float(exp_ass["average_daily_insolation_kWh_per_m2"]), 1e-9):
                    assumptions_ok = False
                if not _float_close(float(ass["electricity_price_usd_per_kWh"]), float(exp_ass["electricity_price_usd_per_kWh"]), 1e-9):
                    assumptions_ok = False
                if int(ass["planned_module_count"]) != int(exp_ass["planned_module_count"]):
                    assumptions_ok = False
            except Exception:
                assumptions_ok = False
            scores["metrics_assumptions_section_correct"] = 1.0 if assumptions_ok else 0.0

            # Design values accuracy
            design_values_ok = True
            tol_eff = 0.001
            tol_power = 0.05
            tol_cpw = 0.002
            tol_area = 0.005
            tol_energy = 0.5
            tol_savings = 0.5
            tol_upfront = 0.1
            tol_payback = 0.01
            try:
                for design in ["baseline", "prototype"]:
                    d = metrics["designs"][design]
                    expd = expected["designs"][design]
                    if not _float_close(float(d["mean_stc_efficiency"]), float(expd["mean_stc_efficiency"]), tol_eff):
                        design_values_ok = False
                        break
                    if not _float_close(float(d["stc_power_W"]), float(expd["stc_power_W"]), tol_power):
                        design_values_ok = False
                        break
                    if not _float_close(float(d["cost_per_watt_usd"]), float(expd["cost_per_watt_usd"]), tol_cpw):
                        design_values_ok = False
                        break
                    if not _float_close(float(d["mean_area_m2"]), float(expd["mean_area_m2"]), tol_area):
                        design_values_ok = False
                        break
                    if not _float_close(float(d["annual_energy_kWh"]), float(expd["annual_energy_kWh"]), tol_energy):
                        design_values_ok = False
                        break
                    if not _float_close(float(d["annual_savings_usd"]), float(expd["annual_savings_usd"]), tol_savings):
                        design_values_ok = False
                        break
                    if not _float_close(float(d["upfront_cost_usd"]), float(expd["upfront_cost_usd"]), tol_upfront):
                        design_values_ok = False
                        break
                    if not _float_close(float(d["payback_years"]), float(expd["payback_years"]), tol_payback):
                        design_values_ok = False
                        break
                scores["metrics_designs_values_accuracy"] = 1.0 if design_values_ok else 0.0
            except Exception:
                scores["metrics_designs_values_accuracy"] = 0.0

            # num_tests
            num_tests_ok = True
            try:
                for design in ["baseline", "prototype"]:
                    d = metrics["designs"][design]
                    expd = expected["designs"][design]
                    if int(d["num_tests"]) != int(expd["num_tests"]):
                        num_tests_ok = False
                        break
                scores["metrics_num_tests_correct"] = 1.0 if num_tests_ok else 0.0
            except Exception:
                scores["metrics_num_tests_correct"] = 0.0

            # prototype_vs_baseline accuracy
            pvb_ok = True
            try:
                m = metrics["prototype_vs_baseline"]
                expm = expected["prototype_vs_baseline"]
                if not _float_close(float(m["efficiency_gain_pct"]), float(expm["efficiency_gain_pct"]), 0.01):
                    pvb_ok = False
                if not _float_close(float(m["payback_improvement_years"]), float(expm["payback_improvement_years"]), 0.01):
                    pvb_ok = False
                scores["metrics_prototype_vs_baseline_accuracy"] = 1.0 if pvb_ok else 0.0
            except Exception:
                scores["metrics_prototype_vs_baseline_accuracy"] = 0.0
        else:
            scores["metrics_assumptions_section_correct"] = 0.0
            scores["metrics_designs_values_accuracy"] = 0.0
            scores["metrics_num_tests_correct"] = 0.0
            scores["metrics_prototype_vs_baseline_accuracy"] = 0.0
    else:
        scores["metrics_file_structure_valid"] = 0.0
        scores["metrics_assumptions_section_correct"] = 0.0
        scores["metrics_designs_values_accuracy"] = 0.0
        scores["metrics_num_tests_correct"] = 0.0
        scores["metrics_prototype_vs_baseline_accuracy"] = 0.0

    # Check email_to_engineering.txt
    email_text = _read_text_safe(out_email_path)
    if email_text is not None:
        # Recipient and references present
        recipient_ok = "eng-team@ourstartup.local" in email_text
        references_ok = ("output/metrics.json" in email_text) and ("output/normalized_per_test.csv" in email_text)
        scores["email_recipient_and_references_present"] = 1.0 if (recipient_ok and references_ok) else 0.0

        # Numbers present (efficiency gain pct and payback improvement years rounded to two decimals)
        numbers_ok = False
        if expected is not None:
            eff_gain = float(expected["prototype_vs_baseline"]["efficiency_gain_pct"])
            payback_impr = float(expected["prototype_vs_baseline"]["payback_improvement_years"])
            eff_candidates = {
                f"{eff_gain:.2f}",
                f"{eff_gain:.2f}%",
                f"{round(eff_gain, 2)}",
                f"{round(eff_gain, 2)}%",
            }
            payback_candidates = {
                f"{payback_impr:.2f}",
                f"{round(payback_impr, 2)}",
            }
            has_eff = any(c in email_text for c in eff_candidates)
            has_payback = any(c in email_text for c in payback_candidates)

            # Also check cost_per_watt_usd for each design (allow common roundings)
            designs_cpw_ok = True
            baseline_cpw = float(expected["designs"]["baseline"]["cost_per_watt_usd"])
            prototype_cpw = float(expected["designs"]["prototype"]["cost_per_watt_usd"])
            baseline_candidates = {
                f"{baseline_cpw:.2f}",
                f"{baseline_cpw:.3f}",
                f"{baseline_cpw:.4f}",
                f"${baseline_cpw:.2f}",
                f"${baseline_cpw:.3f}",
                f"${baseline_cpw:.4f}",
            }
            prototype_candidates = {
                f"{prototype_cpw:.2f}",
                f"{prototype_cpw:.3f}",
                f"{prototype_cpw:.4f}",
                f"${prototype_cpw:.2f}",
                f"${prototype_cpw:.3f}",
                f"${prototype_cpw:.4f}",
            }
            if not any(c in email_text for c in baseline_candidates):
                designs_cpw_ok = False
            if not any(c in email_text for c in prototype_candidates):
                designs_cpw_ok = False

            numbers_ok = has_eff and has_payback and designs_cpw_ok
        scores["email_numbers_present"] = 1.0 if numbers_ok else 0.0

        # Subject mentions findings (efficiency and payback, and prototype/baseline or vs)
        subject_ok = False
        try:
            lines = email_text.splitlines()
            subj_lines = [ln for ln in lines if ln.lower().startswith("subject:")]
            if subj_lines:
                subj = subj_lines[0].lower()
                has_efficiency = "efficiency" in subj
                has_payback = "payback" in subj
                has_context = ("prototype" in subj) or ("baseline" in subj) or ("vs" in subj)
                subject_ok = has_efficiency and has_payback and has_context
            else:
                subject_ok = False
        except Exception:
            subject_ok = False
        scores["email_subject_mentions_findings"] = 1.0 if subject_ok else 0.0
    else:
        scores["email_recipient_and_references_present"] = 0.0
        scores["email_numbers_present"] = 0.0
        scores["email_subject_mentions_findings"] = 0.0

    return scores


def main() -> None:
        workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade(transcript=[], workspace_path=workspace_path)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()