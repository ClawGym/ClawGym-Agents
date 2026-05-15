import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple, Optional


def _safe_load_csv_dicts(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({(k.strip() if isinstance(k, str) else k): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return True, rows
    except Exception:
        return False, []


def _safe_load_json(path: Path) -> Tuple[bool, Optional[dict]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return True, data
    except Exception:
        return False, None


def _safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8")
        return True, text
    except Exception:
        return False, ""


def _parse_float(val) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s == "":
            return None
        s = s.replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _parse_int(val) -> Optional[int]:
    f = _parse_float(val)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def _parse_bool(val) -> Optional[bool]:
    if isinstance(val, bool):
        return val
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in {"true", "t", "1", "yes", "y"}:
        return True
    if s in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _compare_floats(a: float, b: float, rel_tol: float = 1e-3, abs_tol: float = 1e-3) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b), 1.0))


def _run_user_script(workspace: Path) -> Tuple[bool, int]:
    script_path = workspace / "scripts" / "green_space_metrics.py"
    if not script_path.exists():
        return False, -1
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), "input", "outputs"],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        return proc.returncode == 0, proc.returncode
    except Exception:
        return False, -1


def _compute_expected_from_inputs(workspace: Path) -> Tuple[bool, dict, dict]:
    parks_ok, parks_rows = _safe_load_csv_dicts(workspace / "input" / "parks.csv")
    pop_ok, pop_rows = _safe_load_csv_dicts(workspace / "input" / "population.csv")
    env_ok, env_rows = _safe_load_csv_dicts(workspace / "input" / "environment.csv")
    if not (parks_ok and pop_ok and env_ok):
        return False, {}, {}

    pop_by_neigh = {}
    for r in pop_rows:
        n = r.get("neighborhood")
        p = _parse_int(r.get("population"))
        if n and p is not None:
            pop_by_neigh[n] = p

    env_by_neigh = {}
    for r in env_rows:
        n = r.get("neighborhood")
        ast = _parse_float(r.get("asthma_rate_percent"))
        heat = _parse_float(r.get("heat_alert_days"))
        canopy = _parse_float(r.get("tree_canopy_pct"))
        if n and ast is not None and heat is not None and canopy is not None:
            env_by_neigh[n] = {
                "asthma_rate_percent": ast,
                "heat_alert_days": heat,
                "tree_canopy_pct": canopy,
            }

    acres_by_neigh = {}
    for r in parks_rows:
        n = r.get("neighborhood")
        a = _parse_float(r.get("acres"))
        if n and a is not None:
            acres_by_neigh[n] = acres_by_neigh.get(n, 0.0) + a

    neighs = sorted(set(pop_by_neigh.keys()) & set(env_by_neigh.keys()))
    if not neighs:
        return False, {}, {}

    metrics_by_neigh = {}
    for n in neighs:
        pop = pop_by_neigh.get(n)
        env = env_by_neigh.get(n)
        total_acres = acres_by_neigh.get(n, 0.0)
        acres_per_1000 = (total_acres / pop) * 1000.0 if pop and pop > 0 else 0.0
        metrics_by_neigh[n] = {
            "neighborhood": n,
            "total_park_acres": total_acres,
            "population": pop,
            "acres_per_1000": acres_per_1000,
            "tree_canopy_pct": env["tree_canopy_pct"],
            "asthma_rate_percent": env["asthma_rate_percent"],
            "heat_alert_days": env["heat_alert_days"],
            "below_target_acres": acres_per_1000 < 2.0,
        }

    citywide_population = sum(pop_by_neigh[n] for n in neighs)
    total_park_acres_citywide = sum(acres_by_neigh.get(n, 0.0) for n in neighs)
    med_acres = median([metrics_by_neigh[n]["acres_per_1000"] for n in neighs])
    below_cnt = sum(1 for n in neighs if metrics_by_neigh[n]["acres_per_1000"] < 2.0)
    pct_below = (below_cnt / len(neighs)) * 100.0 if neighs else 0.0

    above_group = [metrics_by_neigh[n]["asthma_rate_percent"] for n in neighs if metrics_by_neigh[n]["acres_per_1000"] > med_acres]
    below_group = [metrics_by_neigh[n]["asthma_rate_percent"] for n in neighs if metrics_by_neigh[n]["acres_per_1000"] < med_acres]
    avg_asthma_above = sum(above_group) / len(above_group) if above_group else 0.0
    avg_asthma_below = sum(below_group) / len(below_group) if below_group else 0.0

    canopy_values = [env_by_neigh[n]["tree_canopy_pct"] for n in neighs]
    canopy_median = median(canopy_values)
    top_half_heat = [env_by_neigh[n]["heat_alert_days"] for n in neighs if env_by_neigh[n]["tree_canopy_pct"] > canopy_median]
    bottom_half_heat = [env_by_neigh[n]["heat_alert_days"] for n in neighs if env_by_neigh[n]["tree_canopy_pct"] < canopy_median]
    avg_heat_top = sum(top_half_heat) / len(top_half_heat) if top_half_heat else 0.0
    avg_heat_bottom = sum(bottom_half_heat) / len(bottom_half_heat) if bottom_half_heat else 0.0

    summary = {
        "citywide_population": float(citywide_population),
        "total_park_acres_citywide": float(total_park_acres_citywide),
        "median_acres_per_1000": float(med_acres),
        "pct_neighborhoods_below_target_acres_per_1000": float(pct_below),
        "avg_asthma_rate_above_median_acreage": float(avg_asthma_above),
        "avg_asthma_rate_below_median_acreage": float(avg_asthma_below),
        "avg_heat_days_top_half_canopy": float(avg_heat_top),
        "avg_heat_days_bottom_half_canopy": float(avg_heat_bottom),
    }

    return True, metrics_by_neigh, summary


def _extract_numbers_from_text(text: str) -> List[float]:
    pattern = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b")
    nums = []
    for m in pattern.finditer(text):
        token = m.group(0)
        token_clean = token.replace(",", "")
        try:
            nums.append(float(token_clean))
        except ValueError:
            continue
    return nums


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p.strip()]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_invocation_succeeds": 0.0,
        "metrics_csv_structure": 0.0,
        "metrics_csv_values_correct": 0.0,
        "summary_json_keys_and_numeric": 0.0,
        "summary_json_values_correct": 0.0,
        "brief_exists_and_word_count": 0.0,
        "brief_mentions_health_heat_and_green_canopy": 0.0,
        "brief_cites_at_least_three_json_stats": 0.0,
        "brief_ends_with_actionable_ask": 0.0,
    }

    ran_ok, _rc = _run_user_script(workspace)
    if ran_ok:
        scores["script_invocation_succeeds"] = 1.0

    inputs_ok, expected_metrics_by_neigh, expected_summary = _compute_expected_from_inputs(workspace)

    metrics_path = workspace / "outputs" / "metrics_by_neighborhood.csv"
    metrics_ok, metrics_rows = _safe_load_csv_dicts(metrics_path)
    required_cols = [
        "neighborhood",
        "total_park_acres",
        "population",
        "acres_per_1000",
        "tree_canopy_pct",
        "asthma_rate_percent",
        "heat_alert_days",
        "below_target_acres",
    ]
    if metrics_ok and metrics_rows:
        colnames = [c.strip() for c in (metrics_rows[0].keys())]
        col_set = set(colnames)
        required_set = set(required_cols)
        neighborhoods_in_csv = [row.get("neighborhood") for row in metrics_rows if row.get("neighborhood")]
        unique_neighs_csv = set(neighborhoods_in_csv)
        structure_pass = (col_set == required_set)
        if inputs_ok:
            expected_neighs = set(expected_metrics_by_neigh.keys())
            structure_pass = structure_pass and (set(neighborhoods_in_csv) == expected_neighs) and (len(neighborhoods_in_csv) == len(expected_neighs))
        else:
            structure_pass = structure_pass and (len(neighborhoods_in_csv) == len(unique_neighs_csv))
        scores["metrics_csv_structure"] = 1.0 if structure_pass else 0.0

        if inputs_ok and structure_pass:
            all_good = True
            by_neigh = {row.get("neighborhood"): row for row in metrics_rows if row.get("neighborhood") in expected_metrics_by_neigh}
            for n, expected in expected_metrics_by_neigh.items():
                row = by_neigh.get(n)
                if not row:
                    all_good = False
                    break
                pop_val = _parse_int(row.get("population"))
                if pop_val is None or pop_val != int(expected["population"]):
                    all_good = False
                tpa_val = _parse_float(row.get("total_park_acres"))
                if tpa_val is None or not _compare_floats(tpa_val, expected["total_park_acres"], rel_tol=1e-3, abs_tol=1e-3):
                    all_good = False
                apk_val = _parse_float(row.get("acres_per_1000"))
                if apk_val is None or not _compare_floats(apk_val, expected["acres_per_1000"], rel_tol=1e-2, abs_tol=5e-3):
                    all_good = False
                canopy_val = _parse_float(row.get("tree_canopy_pct"))
                if canopy_val is None or not _compare_floats(canopy_val, expected["tree_canopy_pct"], rel_tol=1e-3, abs_tol=1e-3):
                    all_good = False
                asthma_val = _parse_float(row.get("asthma_rate_percent"))
                if asthma_val is None or not _compare_floats(asthma_val, expected["asthma_rate_percent"], rel_tol=1e-3, abs_tol=1e-3):
                    all_good = False
                heat_val = _parse_float(row.get("heat_alert_days"))
                if heat_val is None or not _compare_floats(heat_val, expected["heat_alert_days"], rel_tol=0, abs_tol=1e-6):
                    all_good = False
                bta_val = _parse_bool(row.get("below_target_acres"))
                if bta_val is None or bta_val != expected["below_target_acres"]:
                    all_good = False
            scores["metrics_csv_values_correct"] = 1.0 if all_good else 0.0
        else:
            scores["metrics_csv_values_correct"] = 0.0
    else:
        scores["metrics_csv_structure"] = 0.0
        scores["metrics_csv_values_correct"] = 0.0

    summary_path = workspace / "outputs" / "summary_stats.json"
    json_ok, json_data = _safe_load_json(summary_path)
    required_json_keys = [
        "citywide_population",
        "total_park_acres_citywide",
        "median_acres_per_1000",
        "pct_neighborhoods_below_target_acres_per_1000",
        "avg_asthma_rate_above_median_acreage",
        "avg_asthma_rate_below_median_acreage",
        "avg_heat_days_top_half_canopy",
        "avg_heat_days_bottom_half_canopy",
    ]
    if json_ok and isinstance(json_data, dict):
        keys_present = all(k in json_data for k in required_json_keys)
        numeric_vals = keys_present and all(isinstance(json_data.get(k), (int, float)) for k in required_json_keys)
        scores["summary_json_keys_and_numeric"] = 1.0 if (keys_present and numeric_vals) else 0.0
        if inputs_ok and keys_present and numeric_vals:
            values_ok = True
            for k in required_json_keys:
                exp = expected_summary.get(k)
                got = float(json_data.get(k))
                rel_tol = 1e-3
                abs_tol = 1e-2 if k != "citywide_population" else 0.5
                if not _compare_floats(got, exp, rel_tol=rel_tol, abs_tol=abs_tol):
                    values_ok = False
            scores["summary_json_values_correct"] = 1.0 if values_ok else 0.0
        else:
            scores["summary_json_values_correct"] = 0.0
    else:
        scores["summary_json_keys_and_numeric"] = 0.0
        scores["summary_json_values_correct"] = 0.0

    brief_path = workspace / "outputs" / "green_spaces_talking_points.md"
    brief_ok, brief_text = _safe_read_text(brief_path)
    if brief_ok and brief_text:
        words = re.findall(r"\b\w+\b", brief_text)
        word_count = len(words)
        if 400 <= word_count <= 600:
            scores["brief_exists_and_word_count"] = 1.0
        else:
            scores["brief_exists_and_word_count"] = 0.0

        lower_text = brief_text.lower()
        has_health = "health" in lower_text
        has_heat = "heat" in lower_text
        has_tree_canopy = ("tree" in lower_text) or ("canopy" in lower_text)
        has_parks_or_green = ("park" in lower_text) or ("green" in lower_text)
        mentions_pass = has_health and has_heat and has_tree_canopy and has_parks_or_green
        scores["brief_mentions_health_heat_and_green_canopy"] = 1.0 if mentions_pass else 0.0

        cites_count = 0
        matched_keys = set()
        if json_ok and isinstance(json_data, dict):
            nums_in_text = _extract_numbers_from_text(brief_text)
            for k in required_json_keys:
                if k not in json_data:
                    continue
                val = _parse_float(json_data[k])
                if val is None:
                    continue
                for num in nums_in_text:
                    if _compare_floats(num, float(val), rel_tol=0.05, abs_tol=0.05):
                        matched_keys.add(k)
                        break
            cites_count = len(matched_keys)
        scores["brief_cites_at_least_three_json_stats"] = 1.0 if cites_count >= 3 else 0.0

        sentences = _split_sentences(brief_text)
        actionable = 0.0
        if sentences:
            last_sentence = sentences[-1].lower()
            verbs = [
                "fund", "funding", "invest", "support", "pass", "approve", "adopt",
                "allocate", "maintain", "expand", "commit", "prioritize", "protect",
                "implement", "increase", "budget", "dedicate"
            ]
            has_action = any(v in last_sentence for v in verbs)
            mentions_council = "council" in last_sentence
            actionable = 1.0 if (has_action and mentions_council) else 0.0
        scores["brief_ends_with_actionable_ask"] = actionable
    else:
        scores["brief_exists_and_word_count"] = 0.0
        scores["brief_mentions_health_heat_and_green_canopy"] = 0.0
        scores["brief_cites_at_least_three_json_stats"] = 0.0
        scores["brief_ends_with_actionable_ask"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()