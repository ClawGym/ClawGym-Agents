import json
import csv
import sys
import math
import re
import importlib.util
from pathlib import Path
from typing import List, Dict, Optional, Any


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for r in reader:
                rows.append(r)
            return rows
    except Exception:
        return None


def _floats_close(a: float, b: float, atol: float = 1e-8, rtol: float = 1e-9) -> bool:
    try:
        return math.isclose(a, b, rel_tol=rtol, abs_tol=atol)
    except Exception:
        return False


def _to_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _import_module_from_path(module_name: str, file_path: Path):
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(file_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        return module
    except Exception:
        return None


def _expected_baseline(tests: List[Dict[str, str]], g0: float) -> Dict[str, Dict[str, float]]:
    # Ideal expansion: Pe_used = Pa; thrust = mdot*Ve; Isp = Ve/g0
    expected: Dict[str, Dict[str, float]] = {}
    for r in tests:
        tid = r.get("test_id", "")
        mdot = _to_float(r.get("mass_flow_rate"))
        Ve = _to_float(r.get("effective_exhaust_velocity"))
        Pa = _to_float(r.get("ambient_pressure"))
        Ae = _to_float(r.get("nozzle_exit_area"))
        if not tid or None in (mdot, Ve, Pa, Ae):
            return {}
        thrust = mdot * Ve
        isp = Ve / g0
        expected[tid] = {
            "exit_pressure_used": Pa,
            "thrust_N": thrust,
            "Isp_s": isp,
        }
    return expected


def _expected_updated(tests: List[Dict[str, str]], g0: float) -> Dict[str, Dict[str, float]]:
    # Non-ideal with measured exit pressure: Pe_used = exit_pressure
    expected: Dict[str, Dict[str, float]] = {}
    for r in tests:
        tid = r.get("test_id", "")
        mdot = _to_float(r.get("mass_flow_rate"))
        Ve = _to_float(r.get("effective_exhaust_velocity"))
        Pa = _to_float(r.get("ambient_pressure"))
        Pe = _to_float(r.get("exit_pressure"))
        Ae = _to_float(r.get("nozzle_exit_area"))
        if not tid or None in (mdot, Ve, Pa, Pe, Ae):
            return {}
        thrust = mdot * Ve + (Pe - Pa) * Ae
        isp = thrust / (mdot * g0)
        expected[tid] = {
            "exit_pressure_used": Pe,
            "thrust_N": thrust,
            "Isp_s": isp,
        }
    return expected


def _parse_results_csv(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    parsed: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        tid = r.get("test_id", "")
        if not tid:
            return {}
        thrust = _to_float(r.get("thrust_N"))
        isp = _to_float(r.get("Isp_s"))
        exit_used = _to_float(r.get("exit_pressure_used"))
        prop = r.get("propellant", "")
        if None in (thrust, isp, exit_used):
            return {}
        parsed[tid] = {
            "thrust_N": thrust,
            "Isp_s": isp,
            "exit_pressure_used": exit_used,
            "propellant": prop,
        }
    return parsed


def _compare_expected_actual(expected: Dict[str, Dict[str, float]], actual: Dict[str, Dict[str, Any]]) -> bool:
    if set(expected.keys()) != set(actual.keys()):
        return False
    for tid, ex in expected.items():
        act = actual.get(tid, {})
        for k in ["exit_pressure_used", "thrust_N", "Isp_s"]:
            if k not in act or k not in ex:
                return False
            if not _floats_close(ex[k], act[k], atol=1e-6, rtol=1e-9):
                return False
    return True


def _load_csv_with_header(path: Path) -> Optional[Dict[str, Any]]:
    rows = _safe_load_csv(path)
    if rows is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, [])
    except Exception:
        header = list(rows[0].keys()) if rows else []
    return {"rows": rows, "header": header}


def _compute_top5_by_propellant(parsed_baseline: Dict[str, Dict[str, Any]],
                                parsed_updated: Dict[str, Dict[str, Any]],
                                tests_meta: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for tid, upd in parsed_updated.items():
        if tid not in parsed_baseline:
            continue
        isp_new = upd["Isp_s"]
        isp_old = parsed_baseline[tid]["Isp_s"]
        prop = upd.get("propellant") or tests_meta.get(tid, {}).get("propellant", "")
        entries.append({
            "test_id": tid,
            "propellant": prop,
            "Isp_new": isp_new,
            "Isp_old": isp_old,
            "delta_Isp": isp_new - isp_old,
        })
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for e in entries:
        grouped.setdefault(e["propellant"], []).append(e)
    out: List[Dict[str, Any]] = []
    for prop, lst in grouped.items():
        lst_sorted = sorted(lst, key=lambda x: (-x["Isp_new"], -x["Isp_old"]))
        for rank, e in enumerate(lst_sorted[:5], start=1):
            out.append({
                "propellant": prop,
                "rank": rank,
                "test_id": e["test_id"],
                "Isp_new": e["Isp_new"],
                "Isp_old": e["Isp_old"],
                "delta_Isp": e["delta_Isp"],
            })
    out.sort(key=lambda x: (str(x["propellant"]), int(x["rank"])))
    return out


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "baseline_results_present": 0.0,
        "baseline_values_correct": 0.0,
        "config_flags_updated": 0.0,
        "code_measured_exit_pressure_fix_implemented": 0.0,
        "code_default_paths_preserved": 0.0,
        "updated_results_present": 0.0,
        "updated_values_correct": 0.0,
        "top5_by_propellant_present": 0.0,
        "top5_by_propellant_correct": 0.0,
        "report_present": 0.0,
        "report_explanation_word_limit": 0.0,
        "report_top5_table_correct": 0.0,
        "report_increase_decrease_counts_correct": 0.0,
    }

    tests_csv = workspace / "input" / "engine_tests.csv"
    config_json = workspace / "input" / "config.json"
    run_sim_py = workspace / "scripts" / "run_sim.py"

    tests_rows = _safe_load_csv(tests_csv)
    config = _safe_load_json(config_json)

    tests_meta: Dict[str, Dict[str, str]] = {}
    if tests_rows:
        for r in tests_rows:
            tid = r.get("test_id", "")
            if tid:
                tests_meta[tid] = {"propellant": r.get("propellant", "")}

    # Determine g0
    g0 = 9.80665
    if config is not None:
        g0_val = _to_float(config.get("g0", 9.80665))
        if g0_val is not None:
            g0 = g0_val

    # Baseline results check
    baseline_path = workspace / "workspace" / "baseline" / "results.csv"
    parsed_baseline: Dict[str, Dict[str, Any]] = {}
    if baseline_path.exists():
        scores["baseline_results_present"] = 1.0
        loaded = _load_csv_with_header(baseline_path)
        if loaded and loaded["rows"] is not None and tests_rows:
            parsed_baseline = _parse_results_csv(loaded["rows"])  # type: ignore[arg-type]
            if parsed_baseline:
                exp_baseline = _expected_baseline(tests_rows, g0)
                if exp_baseline and _compare_expected_actual(exp_baseline, parsed_baseline):
                    scores["baseline_values_correct"] = 1.0

    # Config flags updated
    if config is not None:
        if config.get("use_ideal_expansion") is False and config.get("use_measured_exit_pressure") is True:
            scores["config_flags_updated"] = 1.0

    # Code modification checks (gate on presence of tests and run_sim)
    if run_sim_py.exists() and tests_rows:
        module = _import_module_from_path("run_sim_module_for_check", run_sim_py)
        if module is not None and hasattr(module, "compute_thrust_and_isp"):
            compute_fn = getattr(module, "compute_thrust_and_isp")
            # Pick a row with Pe != Pa
            row_for_check: Optional[Dict[str, str]] = None
            for r in tests_rows:
                try:
                    pa = float(r["ambient_pressure"])
                    pe = float(r["exit_pressure"])
                    if not math.isclose(pa, pe, rel_tol=1e-12, abs_tol=1e-12):
                        row_for_check = r
                        break
                except Exception:
                    continue
            if row_for_check:
                # Check fix: non-ideal + measured => use measured exit pressure and correct thrust/Isp
                cfg_fix = {"use_ideal_expansion": False, "use_measured_exit_pressure": True, "g0": g0}
                try:
                    res = compute_fn(row_for_check, cfg_fix)
                    pe_used = _to_float(res.get("exit_pressure_used"))
                    mdot = _to_float(row_for_check.get("mass_flow_rate"))
                    Ve = _to_float(row_for_check.get("effective_exhaust_velocity"))
                    Pa = _to_float(row_for_check.get("ambient_pressure"))
                    Pe = _to_float(row_for_check.get("exit_pressure"))
                    Ae = _to_float(row_for_check.get("nozzle_exit_area"))
                    thrust = _to_float(res.get("thrust_N"))
                    isp = _to_float(res.get("Isp_s"))
                    if None not in (pe_used, mdot, Ve, Pa, Pe, Ae, thrust, isp):
                        exp_thrust = mdot * Ve + (Pe - Pa) * Ae
                        exp_isp = exp_thrust / (mdot * g0)
                        if _floats_close(pe_used, Pe, atol=1e-6) and _floats_close(thrust, exp_thrust, atol=1e-6) and _floats_close(isp, exp_isp, atol=1e-6):
                            scores["code_measured_exit_pressure_fix_implemented"] = 1.0
                except Exception:
                    pass

                # Check default paths preserved (only if fix implemented to avoid awarding scaffold work)
                if scores["code_measured_exit_pressure_fix_implemented"] > 0.0:
                    ok_default = True
                    # Ideal expansion => Pe_used == Pa
                    try:
                        res_ideal = compute_fn(row_for_check, {"use_ideal_expansion": True, "use_measured_exit_pressure": True, "g0": g0})
                        if not _floats_close(_to_float(res_ideal.get("exit_pressure_used")) or float("inf"),
                                             float(row_for_check["ambient_pressure"]), atol=1e-6):
                            ok_default = False
                    except Exception:
                        ok_default = False
                    # Non-ideal but not measured => Pe_used == Pa
                    try:
                        res_non_meas = compute_fn(row_for_check, {"use_ideal_expansion": False, "use_measured_exit_pressure": False, "g0": g0})
                        if not _floats_close(_to_float(res_non_meas.get("exit_pressure_used")) or float("inf"),
                                             float(row_for_check["ambient_pressure"]), atol=1e-6):
                            ok_default = False
                    except Exception:
                        ok_default = False
                    if ok_default:
                        scores["code_default_paths_preserved"] = 1.0

    # Updated results check
    updated_results_path = workspace / "workspace" / "updated" / "results.csv"
    parsed_updated: Dict[str, Dict[str, Any]] = {}
    if updated_results_path.exists():
        scores["updated_results_present"] = 1.0
        loaded_upd = _load_csv_with_header(updated_results_path)
        if loaded_upd and loaded_upd["rows"] is not None and tests_rows:
            parsed_updated = _parse_results_csv(loaded_upd["rows"])  # type: ignore[arg-type]
            if parsed_updated:
                exp_updated = _expected_updated(tests_rows, g0)
                if exp_updated and _compare_expected_actual(exp_updated, parsed_updated):
                    scores["updated_values_correct"] = 1.0

    # Top5 by propellant
    top5_path = workspace / "workspace" / "updated" / "top5_by_propellant.csv"
    if top5_path.exists():
        scores["top5_by_propellant_present"] = 1.0
        loaded_top5 = _load_csv_with_header(top5_path)
        if loaded_top5 and loaded_top5["rows"] is not None:
            header = loaded_top5["header"]  # type: ignore[assignment]
            rows_top5 = loaded_top5["rows"]  # type: ignore[assignment]
            expected_header = ["propellant", "rank", "test_id", "Isp_new", "Isp_old", "delta_Isp"]
            header_ok = header == expected_header
            if header_ok and parsed_baseline and parsed_updated and scores["baseline_values_correct"] > 0.0 and scores["updated_values_correct"] > 0.0:
                # Build expected
                expected_top5 = _compute_top5_by_propellant(parsed_baseline, parsed_updated, tests_meta)
                # Parse submitted
                try:
                    submitted: List[Dict[str, Any]] = []
                    for r in rows_top5:
                        prop = r.get("propellant", "")
                        rank_str = r.get("rank", "")
                        try:
                            rank = int(float(rank_str))
                        except Exception:
                            submitted = []
                            break
                        tid = r.get("test_id", "")
                        isp_new = _to_float(r.get("Isp_new"))
                        isp_old = _to_float(r.get("Isp_old"))
                        delta = _to_float(r.get("delta_Isp"))
                        if None in (isp_new, isp_old, delta) or not tid:
                            submitted = []
                            break
                        submitted.append({
                            "propellant": prop,
                            "rank": rank,
                            "test_id": tid,
                            "Isp_new": isp_new,
                            "Isp_old": isp_old,
                            "delta_Isp": delta,
                        })
                    submitted.sort(key=lambda x: (str(x["propellant"]), int(x["rank"])))
                    exp_sorted = list(expected_top5)
                    top5_match = len(submitted) == len(exp_sorted)
                    if top5_match:
                        for a, b in zip(submitted, exp_sorted):
                            if a["propellant"] != b["propellant"]:
                                top5_match = False
                                break
                            if int(a["rank"]) != int(b["rank"]):
                                top5_match = False
                                break
                            if a["test_id"] != b["test_id"]:
                                top5_match = False
                                break
                            if not _floats_close(a["Isp_new"], b["Isp_new"], atol=1e-6):
                                top5_match = False
                                break
                            if not _floats_close(a["Isp_old"], b["Isp_old"], atol=1e-6):
                                top5_match = False
                                break
                            if not _floats_close(a["delta_Isp"], b["delta_Isp"], atol=1e-6):
                                top5_match = False
                                break
                    if header_ok and top5_match:
                        scores["top5_by_propellant_correct"] = 1.0
                except Exception:
                    pass

    # Report checks
    report_path = workspace / "workspace" / "report" / "assumption_impact.md"
    if report_path.exists():
        scores["report_present"] = 1.0
        try:
            text = report_path.read_text(encoding="utf-8")
        except Exception:
            text = ""
        # Explanation length: fewer than 150 words before table header
        lines = text.splitlines()
        table_start_idx = None
        for i, line in enumerate(lines):
            l = line.lower()
            if ("test_id" in l) and ("propellant" in l) and ("isp_old" in l) and ("isp_new" in l) and ("delta_isp" in l):
                table_start_idx = i
                break
        explanation = "\n".join(lines[:table_start_idx]) if table_start_idx is not None else text
        if _count_words(explanation) < 150 and _count_words(explanation) > 0:
            scores["report_explanation_word_limit"] = 1.0

        # Top5 absolute delta_Isp table correctness and increase/decrease counts
        if parsed_baseline and parsed_updated and scores["baseline_values_correct"] > 0.0 and scores["updated_values_correct"] > 0.0:
            # Build top5 by absolute delta
            deltas: List[tuple] = []
            for tid, upd_vals in parsed_updated.items():
                if tid not in parsed_baseline:
                    continue
                isp_new = upd_vals["Isp_s"]
                isp_old = parsed_baseline[tid]["Isp_s"]
                prop = upd_vals.get("propellant") or tests_meta.get(tid, {}).get("propellant", "")
                delta = isp_new - isp_old
                deltas.append((tid, prop, isp_old, isp_new, delta, abs(delta)))
            deltas.sort(key=lambda x: (-x[5], x[0]))
            top5 = deltas[:5]
            # Check that all required columns names are present and the 5 test_ids appear
            headers_present = all(h in text.lower() for h in ["test_id", "propellant", "isp_old", "isp_new", "delta_isp"])
            ids_present = all(tid in text for (tid, _, _, _, _, _) in top5) if top5 else False
            if headers_present and ids_present:
                scores["report_top5_table_correct"] = 1.0
            # Increase/decrease counts
            inc = sum(1 for (_tid, _prop, old, new, _d, _ad) in deltas if new > old)
            dec = sum(1 for (_tid, _prop, old, new, _d, _ad) in deltas if new < old)
            inc_ok = False
            dec_ok = False
            for line in lines:
                l = line.lower()
                # look for numeric tokens
                nums = re.findall(r"\b\d+\b", line)
                if "increase" in l and str(inc) in nums:
                    inc_ok = True
                if "decrease" in l and str(dec) in nums:
                    dec_ok = True
            if inc_ok and dec_ok:
                scores["report_increase_decrease_counts_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()