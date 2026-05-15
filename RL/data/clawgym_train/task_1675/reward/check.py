import json
import csv
import sys
import math
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _to_number(val: Any) -> Optional[float]:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            v = val.strip().replace(",", "")
            if v == "":
                return None
            return float(v)
        return None
    except Exception:
        return None


def _almost_equal(a: float, b: float, tol: float = 1e-3) -> bool:
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    if n % 2 == 1:
        return float(vals[mid])
    else:
        return (vals[mid - 1] + vals[mid]) / 2.0


def _simple_yaml_load(path: Path) -> Optional[Dict[str, Any]]:
    # Minimal YAML loader that supports nested dicts with 2-space indentation and simple scalars
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    result: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, result)]
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        level = indent // 2
        content = line.strip()
        if ":" not in content:
            return None
        key, val = content.split(":", 1)
        key = key.strip()
        val = val.strip()
        while len(stack) > level + 1:
            stack.pop()
        current = stack[-1][1]
        if val == "":
            new_dict: Dict[str, Any] = {}
            current[key] = new_dict
            stack.append((level + 1, new_dict))
        else:
            scalar: Any
            try:
                lv = val.lower()
                if lv in ("true", "false"):
                    scalar = True if lv == "true" else False
                else:
                    if any(ch in val for ch in [".", "e", "E"]):
                        scalar = float(val)
                    else:
                        scalar = int(val)
            except Exception:
                scalar = val
            current[key] = scalar
    return result


def _compute_expected_metrics(survey_rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, float]]]:
    try:
        villages: Dict[str, Dict[str, Any]] = {}
        for r in survey_rows:
            village = r.get("village", "").strip()
            if not village:
                return None
            if village not in villages:
                villages[village] = {
                    "households": 0,
                    "water": [],
                    "resp_yes": 0,
                    "distance": [],
                    "fuel_spend": [],
                    "can_pay_20": 0,
                }
            v = villages[village]
            v["households"] += 1
            wm = _to_number(r.get("water_minutes_per_day", ""))
            if wm is None:
                return None
            v["water"].append(wm)
            resp = (r.get("respiratory_symptoms") or "").strip().lower()
            if resp == "yes":
                v["resp_yes"] += 1
            elif resp == "no":
                pass
            else:
                # treat unknown as invalid
                return None
            dist = _to_number(r.get("distance_to_clinic_km", ""))
            if dist is None:
                return None
            v["distance"].append(dist)
            fuel = _to_number(r.get("weekly_fuel_spend_usd", ""))
            if fuel is None:
                return None
            v["fuel_spend"].append(fuel)
            canpay = _to_number(r.get("can_pay_cookstove_usd", ""))
            if canpay is None:
                return None
            if canpay >= 20:
                v["can_pay_20"] += 1
        expected: Dict[str, Dict[str, float]] = {}
        for village, data in villages.items():
            hh = data["households"]
            if hh == 0:
                return None
            avg_water = sum(data["water"]) / hh
            pct_resp = data["resp_yes"] / hh
            avg_distance = sum(data["distance"]) / hh
            median_fuel = _median(data["fuel_spend"])
            if median_fuel is None:
                return None
            pct_can_pay = data["can_pay_20"] / hh
            expected[village] = {
                "households": float(hh),
                "avg_water_minutes": float(avg_water),
                "pct_respiratory": float(pct_resp),
                "avg_distance_to_clinic_km": float(avg_distance),
                "median_weekly_fuel_spend_usd": float(median_fuel),
                "pct_can_pay_20usd_plus": float(pct_can_pay),
            }
        return expected
    except Exception:
        return None


def _compute_expected_recommendations(
    expected_metrics: Dict[str, Dict[str, float]],
    constraints: Dict[str, Any],
    interventions_rows: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    try:
        thresholds = constraints.get("thresholds", {})
        allocation = constraints.get("allocation", {})
        budget_usd = constraints.get("budget_usd", None)
        if budget_usd is None:
            return None
        unit_costs: Dict[str, float] = {}
        for r in interventions_rows:
            name = (r.get("intervention") or "").strip()
            cost = _to_number(r.get("unit_cost_usd", ""))
            if name and cost is not None:
                unit_costs[name] = float(cost)
        water_thr = float(thresholds.get("water_minutes_high", float("inf")))
        resp_thr = float(thresholds.get("respiratory_pct_high", float("inf")))
        dist_thr = float(thresholds.get("distance_to_clinic_high_km", float("inf")))
        frac_ck = float(allocation.get("chlorine_kits_target_fraction", 0.0))
        frac_ct = float(allocation.get("cookstove_training_target_fraction", 0.0))
        visits_per_month_raw = allocation.get("mobile_clinic_visits_per_month", 0)
        try:
            visits_per_month = int(visits_per_month_raw)
        except Exception:
            visits_per_month = 0
        villages_out: List[Dict[str, Any]] = []
        total_cost = 0.0
        for village, m in expected_metrics.items():
            hh = int(round(m["households"]))
            avg_water = m["avg_water_minutes"]
            pct_resp = m["pct_respiratory"]
            avg_dist = m["avg_distance_to_clinic_km"]
            rec = "none"
            units = 0
            if avg_water >= water_thr:
                rec = "chlorine_kit"
                units = math.ceil(hh * frac_ck)
            elif pct_resp >= resp_thr:
                rec = "cookstove_training"
                units = math.ceil(hh * frac_ct)
            elif avg_dist >= dist_thr:
                rec = "mobile_clinic_outreach"
                units = visits_per_month
            unit_cost = 0.0
            if rec != "none":
                unit_cost = float(unit_costs.get(rec, 0.0))
            est_cost = float(units) * unit_cost
            total_cost += est_cost
            villages_out.append({
                "village": village,
                "households": hh,
                "metrics": {
                    "avg_water_minutes": m["avg_water_minutes"],
                    "pct_respiratory": m["pct_respiratory"],
                    "avg_distance_to_clinic_km": m["avg_distance_to_clinic_km"],
                    "median_weekly_fuel_spend_usd": m["median_weekly_fuel_spend_usd"],
                    "pct_can_pay_20usd_plus": m["pct_can_pay_20usd_plus"],
                },
                "recommended_intervention": rec,
                "units": units,
                "unit_cost_usd": unit_cost,
                "estimated_cost_usd": est_cost,
            })
        budget_status = "Within budget" if total_cost <= float(budget_usd) else "Exceeds budget"
        out = {
            "villages": villages_out,
            "total_estimated_cost_usd": total_cost,
            "budget_usd": float(budget_usd),
            "budget_status": budget_status,
        }
        return out
    except Exception:
        return None


def _extract_number_after_dollar(s: str) -> Optional[float]:
    m = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "aggregated_metrics_file": 0.0,
        "aggregated_metrics_columns_order": 0.0,
        "aggregated_metrics_villages_match": 0.0,
        "aggregated_metrics_values_correct": 0.0,
        "recommendations_json_file": 0.0,
        "recommendations_structure_valid": 0.0,
        "recommendations_villages_match": 0.0,
        "recommendations_values_correct": 0.0,
        "recommendations_budget_status": 0.0,
        "brief_file": 0.0,
        "brief_no_placeholders": 0.0,
        "brief_survey_coverage_replacements": 0.0,
        "brief_max_burdens_replacements": 0.0,
        "brief_agg_csv_path_replacement": 0.0,
        "brief_budget_replacements": 0.0,
        "brief_recommendations_bullets_correct": 0.0,
        "cross_metrics_consistency_csv_json": 0.0,
    }

    # Load inputs
    survey_path = workspace / "input" / "household_survey.csv"
    constraints_path = workspace / "input" / "constraints.yaml"
    interventions_path = workspace / "input" / "interventions.csv"
    draft_brief_path = workspace / "input" / "draft_brief.md"

    survey_rows = _safe_read_csv(survey_path) or []
    interventions_rows = _safe_read_csv(interventions_path) or []
    constraints = _simple_yaml_load(constraints_path) or {}

    expected_metrics = None
    if survey_rows:
        expected_metrics = _compute_expected_metrics(survey_rows)

    expected_recommendations = None
    if expected_metrics is not None and constraints and interventions_rows:
        expected_recommendations = _compute_expected_recommendations(expected_metrics, constraints, interventions_rows)

    expected_villages = set(expected_metrics.keys()) if expected_metrics else set()
    total_households_expected = 0
    if expected_metrics:
        total_households_expected = int(sum(int(round(v["households"])) for v in expected_metrics.values()))

    # 1) aggregated_metrics.csv checks
    agg_path = workspace / "output" / "aggregated_metrics.csv"
    if agg_path.exists():
        scores["aggregated_metrics_file"] = 1.0
        agg_rows = _safe_read_csv(agg_path)
        if agg_rows is not None:
            # header order check
            try:
                with agg_path.open("r", encoding="utf-8") as f:
                    header_line = f.readline().strip()
                expected_header = "village,households,avg_water_minutes,pct_respiratory,avg_distance_to_clinic_km,median_weekly_fuel_spend_usd,pct_can_pay_20usd_plus"
                if header_line == expected_header:
                    scores["aggregated_metrics_columns_order"] = 1.0
            except Exception:
                pass
            # villages match
            villages_in_csv = set()
            try:
                for r in agg_rows:
                    vname = (r.get("village") or "").strip()
                    if vname:
                        villages_in_csv.add(vname)
                if expected_villages and villages_in_csv == expected_villages:
                    scores["aggregated_metrics_villages_match"] = 1.0
            except Exception:
                pass
            # values correct
            values_ok = True
            if expected_metrics is not None and agg_rows is not None:
                csv_map: Dict[str, Dict[str, Any]] = {}
                for r in agg_rows:
                    vname = (r.get("village") or "").strip()
                    if not vname:
                        values_ok = False
                        break
                    csv_map[vname] = r
                if values_ok and expected_villages.issubset(set(csv_map.keys())) and expected_villages:
                    for vname, exp in expected_metrics.items():
                        row = csv_map.get(vname)
                        if row is None:
                            values_ok = False
                            break
                        hh_val = _to_number(row.get("households", ""))
                        if hh_val is None or not _almost_equal(hh_val, exp["households"]):
                            values_ok = False
                            break
                        for key_csv, key_exp in [
                            ("avg_water_minutes", "avg_water_minutes"),
                            ("pct_respiratory", "pct_respiratory"),
                            ("avg_distance_to_clinic_km", "avg_distance_to_clinic_km"),
                            ("median_weekly_fuel_spend_usd", "median_weekly_fuel_spend_usd"),
                            ("pct_can_pay_20usd_plus", "pct_can_pay_20usd_plus"),
                        ]:
                            v = _to_number(row.get(key_csv, ""))
                            if v is None or not _almost_equal(v, exp[key_exp]):
                                values_ok = False
                                break
                        if not values_ok:
                            break
                else:
                    values_ok = False
            else:
                values_ok = False
            if values_ok:
                scores["aggregated_metrics_values_correct"] = 1.0

    # 2) recommendations.json checks
    rec_path = workspace / "output" / "recommendations.json"
    rec_json = _safe_load_json(rec_path) if rec_path.exists() else None
    if rec_path.exists():
        scores["recommendations_json_file"] = 1.0
    if rec_json is not None and isinstance(rec_json, dict):
        # Basic structure
        structure_ok = True
        if not isinstance(rec_json.get("villages"), list):
            structure_ok = False
        if "total_estimated_cost_usd" not in rec_json or "budget_usd" not in rec_json or "budget_status" not in rec_json:
            structure_ok = False
        if structure_ok:
            scores["recommendations_structure_valid"] = 1.0
        # Villages match
        try:
            rec_villages_list = rec_json.get("villages", [])
            rec_villages_set = set()
            for item in rec_villages_list:
                if isinstance(item, dict) and "village" in item:
                    rec_villages_set.add(str(item["village"]))
            if expected_villages and rec_villages_set == expected_villages:
                scores["recommendations_villages_match"] = 1.0
        except Exception:
            pass
        # Values correct per village
        values_ok = True
        if expected_recommendations is not None and isinstance(rec_json.get("villages"), list):
            exp_map: Dict[str, Dict[str, Any]] = {}
            for item in expected_recommendations["villages"]:
                exp_map[item["village"]] = item
            unit_costs_lookup: Dict[str, float] = {}
            for r in interventions_rows:
                name = (r.get("intervention") or "").strip()
                cost = _to_number(r.get("unit_cost_usd", ""))
                if name and cost is not None:
                    unit_costs_lookup[name] = float(cost)
            for item in rec_json["villages"]:
                if not isinstance(item, dict):
                    values_ok = False
                    break
                vname = item.get("village")
                if vname not in exp_map:
                    values_ok = False
                    break
                exp_item = exp_map[vname]
                hh = _to_number(item.get("households"))
                if hh is None or not _almost_equal(hh, exp_item["households"]):
                    values_ok = False
                    break
                met = item.get("metrics", {})
                if not isinstance(met, dict):
                    values_ok = False
                    break
                for k in ["avg_water_minutes", "pct_respiratory", "avg_distance_to_clinic_km", "median_weekly_fuel_spend_usd", "pct_can_pay_20usd_plus"]:
                    mv = _to_number(met.get(k))
                    if mv is None or not _almost_equal(mv, exp_item["metrics"][k]):
                        values_ok = False
                        break
                if not values_ok:
                    break
                rec_int = item.get("recommended_intervention")
                if rec_int != exp_item["recommended_intervention"]:
                    values_ok = False
                    break
                units = _to_number(item.get("units"))
                if units is None or not _almost_equal(units, exp_item["units"]):
                    values_ok = False
                    break
                unit_cost = _to_number(item.get("unit_cost_usd"))
                if rec_int == "none":
                    if unit_cost is None or not _almost_equal(unit_cost, 0.0):
                        values_ok = False
                        break
                else:
                    expected_cost = unit_costs_lookup.get(rec_int, None)
                    if expected_cost is None or unit_cost is None or not _almost_equal(unit_cost, expected_cost):
                        values_ok = False
                        break
                est_cost = _to_number(item.get("estimated_cost_usd"))
                if est_cost is None or not _almost_equal(est_cost, exp_item["estimated_cost_usd"]):
                    values_ok = False
                    break
        else:
            values_ok = False
        if values_ok:
            scores["recommendations_values_correct"] = 1.0

        # Budget totals
        budget_ok = False
        try:
            total_cost = _to_number(rec_json.get("total_estimated_cost_usd"))
            budget_usd = _to_number(rec_json.get("budget_usd"))
            budget_status = rec_json.get("budget_status")
            if expected_recommendations is not None and total_cost is not None and budget_usd is not None:
                exp_total = expected_recommendations["total_estimated_cost_usd"]
                exp_budget = expected_recommendations["budget_usd"]
                exp_status = expected_recommendations["budget_status"]
                if _almost_equal(total_cost, exp_total) and _almost_equal(budget_usd, exp_budget) and str(budget_status) == exp_status:
                    budget_ok = True
        except Exception:
            budget_ok = False
        if budget_ok:
            scores["recommendations_budget_status"] = 1.0

    # Cross-file consistency: CSV vs JSON metrics
    cross_ok = False
    agg_rows_present = _safe_read_csv(agg_path) if agg_path.exists() else None
    if agg_rows_present and rec_json and isinstance(rec_json.get("villages"), list):
        try:
            csv_map = { (r.get("village") or "").strip(): r for r in agg_rows_present }
            json_map = { (d.get("village") or "").strip(): d for d in rec_json["villages"] if isinstance(d, dict) }
            if set(csv_map.keys()) == set(json_map.keys()) and csv_map:
                agree = True
                for vname in csv_map.keys():
                    r = csv_map[vname]
                    j = json_map[vname]
                    hh_csv = _to_number(r.get("households", ""))
                    hh_json = _to_number(j.get("households"))
                    if hh_csv is None or hh_json is None or not _almost_equal(hh_csv, hh_json):
                        agree = False
                        break
                    met = j.get("metrics", {})
                    for key_csv, key_json in [
                        ("avg_water_minutes", "avg_water_minutes"),
                        ("pct_respiratory", "pct_respiratory"),
                        ("avg_distance_to_clinic_km", "avg_distance_to_clinic_km"),
                        ("median_weekly_fuel_spend_usd", "median_weekly_fuel_spend_usd"),
                        ("pct_can_pay_20usd_plus", "pct_can_pay_20usd_plus"),
                    ]:
                        cval = _to_number(r.get(key_csv, ""))
                        jval = _to_number(met.get(key_json))
                        if cval is None or jval is None or not _almost_equal(cval, jval):
                            agree = False
                            break
                    if not agree:
                        break
                cross_ok = agree
        except Exception:
            cross_ok = False
    if cross_ok:
        scores["cross_metrics_consistency_csv_json"] = 1.0

    # 3) Brief updated markdown checks
    brief_path = workspace / "output" / "draft_brief_updated.md"
    brief_text = _safe_read_text(brief_path) if brief_path.exists() else None
    if brief_path.exists():
        scores["brief_file"] = 1.0
    if brief_text is not None:
        # placeholders replaced
        if "{{" not in brief_text and "}}" not in brief_text:
            scores["brief_no_placeholders"] = 1.0

        # Survey coverage line
        survey_cov_ok = False
        try:
            lines = brief_text.splitlines()
            line_cov = None
            for ln in lines:
                if ln.strip().startswith("Survey coverage:"):
                    line_cov = ln.strip()
                    break
            if line_cov and expected_villages:
                m = re.search(r"Survey coverage:\s*([0-9]+)\s*households across\s*(.+?)\.", line_cov)
                if m:
                    tot = int(m.group(1))
                    vlist_str = m.group(2)
                    vlist = [v.strip() for v in vlist_str.split(",") if v.strip()]
                    if set(vlist) == expected_villages and tot == total_households_expected:
                        survey_cov_ok = True
        except Exception:
            survey_cov_ok = False
        if survey_cov_ok:
            scores["brief_survey_coverage_replacements"] = 1.0

        # Max burdens lines
        max_ok = False
        try:
            line_water = None
            line_resp = None
            for ln in brief_text.splitlines():
                lns = ln.strip()
                if lns.startswith("- Water collection time is highest in"):
                    line_water = lns
                if lns.startswith("- Respiratory symptoms are most prevalent in"):
                    line_resp = lns
            if expected_metrics and line_water and line_resp:
                mw = re.search(r"highest in\s*(.+?)\s*\(avg\s*([0-9]+(?:\.[0-9]+)?)\s*minutes/day\)", line_water)
                mr = re.search(r"most prevalent in\s*(.+?)\s*\(\s*([0-9]+(?:\.[0-9]+)?)\s*of households\)", line_resp)
                if mw and mr:
                    v_water = mw.group(1).strip()
                    water_val = float(mw.group(2))
                    v_resp = mr.group(1).strip()
                    resp_val = float(mr.group(2))
                    max_water_v = max(expected_metrics.items(), key=lambda kv: kv[1]["avg_water_minutes"])[0]
                    max_water_val = expected_metrics[max_water_v]["avg_water_minutes"]
                    max_resp_v = max(expected_metrics.items(), key=lambda kv: kv[1]["pct_respiratory"])[0]
                    max_resp_val = expected_metrics[max_resp_v]["pct_respiratory"]
                    if v_water == max_water_v and _almost_equal(water_val, max_water_val) and v_resp == max_resp_v and _almost_equal(resp_val, max_resp_val):
                        max_ok = True
        except Exception:
            max_ok = False
        if max_ok:
            scores["brief_max_burdens_replacements"] = 1.0

        # AGG_CSV_PATH
        if "output/aggregated_metrics.csv" in brief_text:
            scores["brief_agg_csv_path_replacement"] = 1.0

        # Budget summary
        budget_ok = False
        try:
            lines = brief_text.splitlines()
            line_est = None
            line_status = None
            for ln in lines:
                lns = ln.strip()
                if lns.startswith("- Estimated monthly need for immediate actions:"):
                    line_est = lns
                if lns.startswith("- Budget status:"):
                    line_status = lns
            if line_est and line_status and expected_recommendations is not None:
                est_val = _extract_number_after_dollar(line_est)
                status_val = line_status.split(":", 1)[1].strip() if ":" in line_status else None
                if status_val is not None:
                    status_val = status_val.rstrip(".").strip()
                if est_val is not None and _almost_equal(est_val, expected_recommendations["total_estimated_cost_usd"]) and status_val == expected_recommendations["budget_status"]:
                    budget_ok = True
        except Exception:
            budget_ok = False
        if budget_ok:
            scores["brief_budget_replacements"] = 1.0

        # Recommendations bullets
        bullets_ok = False
        try:
            lines = brief_text.splitlines()
            rec_start_idx = None
            notes_idx = None
            for i, ln in enumerate(lines):
                if ln.strip().startswith("Recommended immediate actions (one per village):"):
                    rec_start_idx = i
                if ln.strip().startswith("Notes:"):
                    notes_idx = i
                    break
            bullet_lines: List[str] = []
            if rec_start_idx is not None:
                for j in range(rec_start_idx + 1, len(lines) if notes_idx is None else notes_idx):
                    l = lines[j].rstrip()
                    if l.strip().startswith("- "):
                        bullet_lines.append(l.strip())
            if expected_recommendations is not None and bullet_lines:
                exp_map = {v["village"]: v for v in expected_recommendations["villages"]}
                seen_villages: set = set()
                parsed_ok = True
                for bl in bullet_lines:
                    m = re.match(r"-\s*(.*?):\s*([a-zA-Z_]+)\s*\(\s*([0-9]+)\s*units,\s*est\.\s*\$([0-9]+(?:\.[0-9]+)?)\s*\)", bl)
                    if not m:
                        parsed_ok = False
                        break
                    vname = m.group(1).strip()
                    rec = m.group(2).strip()
                    units = float(m.group(3))
                    cost = float(m.group(4))
                    seen_villages.add(vname)
                    if vname not in exp_map:
                        parsed_ok = False
                        break
                    exp = exp_map[vname]
                    if rec != exp["recommended_intervention"]:
                        parsed_ok = False
                        break
                    if not _almost_equal(units, float(exp["units"])):
                        parsed_ok = False
                        break
                    if not _almost_equal(cost, float(exp["estimated_cost_usd"])):
                        parsed_ok = False
                        break
                if parsed_ok and seen_villages == set(exp_map.keys()):
                    bullets_ok = True
        except Exception:
            bullets_ok = False
        if bullets_ok:
            scores["brief_recommendations_bullets_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()