import csv
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                return row
            return []
    except Exception:
        return None


def _safe_int(s: str) -> Optional[int]:
    try:
        if s is None:
            return None
        s = s.strip()
        if s == "":
            return None
        if re.fullmatch(r"[-+]?\d+", s):
            return int(s)
        # If it looks like a float but is integer value
        if re.fullmatch(r"[-+]?\d+(\.\d+)?", s):
            val = float(s)
            if abs(val - int(round(val))) < 1e-9:
                return int(round(val))
            return None
        return None
    except Exception:
        return None


def _safe_float(s: str) -> Optional[float]:
    try:
        if s is None:
            return None
        s = s.strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _is_blank(s: Optional[str]) -> bool:
    return s is None or (isinstance(s, str) and s.strip() == "")


def _parse_date_iso(s: str) -> Optional[datetime.date]:
    try:
        return datetime.fromisoformat(s.strip()).date()
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _discover_input_csvs(workspace: Path) -> List[Path]:
    matches_dir = workspace / "input" / "matches"
    if not matches_dir.exists():
        return []
    return sorted(matches_dir.rglob("*.csv"))


def _extract_season_from_filename(path: Path) -> Optional[str]:
    m = re.search(r"(\d{4})", path.name)
    return m.group(1) if m else None


def _load_input_data(workspace: Path) -> Tuple[Dict[str, List[Dict]], bool]:
    """Returns (season_to_rows, ok). Each row dict contains fields parsed from input."""
    season_to_rows: Dict[str, List[Dict]] = {}
    ok = True
    files = _discover_input_csvs(workspace)
    for f in files:
        season = _extract_season_from_filename(f)
        if not season:
            ok = False
            continue
        rows = _read_csv_dicts(f)
        if rows is None:
            ok = False
            continue
        parsed_rows: List[Dict] = []
        for r in rows:
            date_str = r.get("date")
            opponent = r.get("opponent")
            home_away = r.get("home_away")
            gf = _safe_int(str(r.get("goals_for", "")).strip() if r.get("goals_for") is not None else "")
            ga = _safe_int(str(r.get("goals_against", "")).strip() if r.get("goals_against") is not None else "")
            sot = _safe_int(str(r.get("shots_on_target", "")).strip() if r.get("shots_on_target") is not None else "")
            pcp = _safe_int(str(r.get("pass_completion_pct", "")).strip() if r.get("pass_completion_pct") is not None else "")
            d = _parse_date_iso(date_str or "")
            if None in (d, opponent, home_away, gf, ga, sot, pcp):
                ok = False
                continue
            parsed_rows.append({
                "season": season,
                "date": d,
                "date_str": d.isoformat(),
                "opponent": opponent,
                "home_away": home_away,
                "goals_for": gf,
                "goals_against": ga,
                "shots_on_target": sot,
                "pass_completion_pct": pcp,
            })
        parsed_rows.sort(key=lambda x: x["date"])
        season_to_rows.setdefault(season, []).extend(parsed_rows)
    return season_to_rows, ok


def _compute_expected_combined(season_to_rows: Dict[str, List[Dict]]) -> Dict[Tuple[str, str, str, str], Dict]:
    """Compute expected goal_diff and rolling 5 metrics. Returns mapping by key."""
    expected: Dict[Tuple[str, str, str, str], Dict] = {}
    for season, rows in season_to_rows.items():
        # Precompute series
        goal_diff_series = [r["goals_for"] - r["goals_against"] for r in rows]
        shots_series = [r["shots_on_target"] for r in rows]
        pass_series = [r["pass_completion_pct"] for r in rows]
        n = len(rows)
        for i, r in enumerate(rows):
            gd = goal_diff_series[i]
            # rolling for i >= 4
            if i >= 4:
                gd_roll = sum(goal_diff_series[i-4:i+1]) / 5.0
                sot_roll = sum(shots_series[i-4:i+1]) / 5.0
                pcp_roll = sum(pass_series[i-4:i+1]) / 5.0
            else:
                gd_roll = None
                sot_roll = None
                pcp_roll = None
            key = (str(season), r["date_str"], r["opponent"], r["home_away"])
            expected[key] = {
                "season": str(season),
                "date": r["date_str"],
                "opponent": r["opponent"],
                "home_away": r["home_away"],
                "goals_for": r["goals_for"],
                "goals_against": r["goals_against"],
                "shots_on_target": r["shots_on_target"],
                "pass_completion_pct": r["pass_completion_pct"],
                "goal_diff": gd,
                "rolling5_goal_diff": gd_roll,
                "rolling5_shots_on_target": sot_roll,
                "rolling5_pass_completion_pct": pcp_roll,
            }
    return expected


def _expected_trend_summary(expected_combined: Dict[Tuple[str, str, str, str], Dict]) -> Dict[Tuple[str, str], Dict]:
    """Compute expected season-level trend summary from expected combined values."""
    # Group by season, and for each metric collect ordered rolling values by date order.
    season_metric_values: Dict[str, Dict[str, List[Tuple[str, Optional[float]]]]] = {}
    for (season, date_str, opponent, ha), rec in expected_combined.items():
        season_metric_values.setdefault(season, {}).setdefault("goal_diff", []).append((date_str, rec["rolling5_goal_diff"]))
        season_metric_values.setdefault(season, {}).setdefault("shots_on_target", []).append((date_str, rec["rolling5_shots_on_target"]))
        season_metric_values.setdefault(season, {}).setdefault("pass_completion_pct", []).append((date_str, rec["rolling5_pass_completion_pct"]))

    expected_summary: Dict[Tuple[str, str], Dict] = {}
    for season, metrics in season_metric_values.items():
        for metric, vals in metrics.items():
            vals_sorted = sorted(vals, key=lambda t: t[0])
            # Find first and last non-None
            first = None
            last = None
            for _, v in vals_sorted:
                if v is not None:
                    first = v
                    break
            for _, v in reversed(vals_sorted):
                if v is not None:
                    last = v
                    break
            if first is None or last is None:
                # No full windows; skip (unlikely with provided inputs)
                continue
            delta = last - first
            if _float_equal(last, first):
                direction = "flat"
            elif last > first:
                direction = "up"
            else:
                direction = "down"
            expected_summary[(season, metric)] = {
                "season": season,
                "metric": metric,
                "first_trailing5": first,
                "last_trailing5": last,
                "delta": delta,
                "direction": direction,
            }
    return expected_summary


def _find_script(workspace: Path) -> Optional[Path]:
    """Find script at scripts/analyze_trends with allowed extensions."""
    scripts_dir = workspace / "scripts"
    candidates = [
        scripts_dir / "analyze_trends",
        scripts_dir / "analyze_trends.py",
        scripts_dir / "analyze_trends.R",
        scripts_dir / "analyze_trends.sh",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    # try any file named analyze_trends.* in scripts
    if scripts_dir.exists() and scripts_dir.is_dir():
        for p in scripts_dir.iterdir():
            if p.is_file() and p.name.startswith("analyze_trends"):
                return p
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "run_command_present": 0.0,
        "combined_exists": 0.0,
        "combined_header_correct": 0.0,
        "combined_contains_all_rows": 0.0,
        "combined_sorted_within_season": 0.0,
        "base_values_correct": 0.0,
        "goal_diff_values_correct": 0.0,
        "rolling5_goal_diff_correct": 0.0,
        "rolling5_shots_on_target_correct": 0.0,
        "rolling5_pass_completion_pct_correct": 0.0,
        "trend_exists": 0.0,
        "trend_header_correct": 0.0,
        "trend_row_count_correct": 0.0,
        "trend_values_correct": 0.0,
        "trend_directions_correct": 0.0,
    }

    # Script presence
    script_path = _find_script(workspace)
    if script_path is not None:
        scores["script_exists"] = 1.0

    # Run command presence
    run_cmd_path = workspace / "output" / "run_command.txt"
    if run_cmd_path.exists():
        try:
            content = run_cmd_path.read_text(encoding="utf-8").splitlines()
            # Accept one non-empty line; ignore trailing empty lines
            non_empty = [ln for ln in content if ln.strip() != ""]
            if len(non_empty) >= 1:
                # Use first non-empty line
                line = non_empty[0]
                if "scripts/analyze_trends" in line.replace("\\", "/"):
                    scores["run_command_present"] = 1.0
        except Exception:
            pass

    # Load inputs to compute expected
    season_to_rows, inputs_ok = _load_input_data(workspace)
    expected_combined = _compute_expected_combined(season_to_rows)
    expected_keys = set(expected_combined.keys())
    seasons_expected = sorted(set([k[0] for k in expected_keys]))
    # Combined output checks
    combined_path = workspace / "output" / "combined_with_rolling.csv"
    if combined_path.exists():
        scores["combined_exists"] = 1.0
        header = _read_csv_header(combined_path)
        expected_header = [
            "season",
            "date",
            "opponent",
            "home_away",
            "goals_for",
            "goals_against",
            "shots_on_target",
            "pass_completion_pct",
            "goal_diff",
            "rolling5_goal_diff",
            "rolling5_shots_on_target",
            "rolling5_pass_completion_pct",
        ]
        if header is not None and header == expected_header:
            scores["combined_header_correct"] = 1.0

        rows = _read_csv_dicts(combined_path)
        if rows is not None:
            # Build student keys
            student_keys = set()
            student_by_key = {}
            per_season_dates_in_order: Dict[str, List[str]] = {}
            base_values_match = True
            gd_values_match = True
            roll_gd_match = True
            roll_sot_match = True
            roll_pcp_match = True
            # Validate presence of required columns
            required_cols = set(expected_header)
            if all(col in rows[0].keys() for col in expected_header):
                for r in rows:
                    season_str = str(r.get("season", "")).strip()
                    date_str = r.get("date", "")
                    opponent = r.get("opponent", "")
                    ha = r.get("home_away", "")
                    key = (season_str, date_str, opponent, ha)
                    student_keys.add(key)
                    student_by_key[key] = r
                    per_season_dates_in_order.setdefault(season_str, []).append(date_str)

                # Contains all rows
                if expected_keys and student_keys == expected_keys:
                    scores["combined_contains_all_rows"] = 1.0
                elif not expected_keys and len(student_keys) == 0:
                    # No inputs, no expected rows: consider pass
                    scores["combined_contains_all_rows"] = 1.0

                # Sorted within season
                sorted_within = True
                for season, date_list in per_season_dates_in_order.items():
                    # Only assess for seasons we have expected data for
                    # Parse dates and check non-decreasing
                    prev = None
                    for dstr in date_list:
                        d = _parse_date_iso(dstr)
                        if d is None:
                            sorted_within = False
                            break
                        if prev is not None and d < prev:
                            sorted_within = False
                            break
                        prev = d
                    if not sorted_within:
                        break
                if sorted_within:
                    scores["combined_sorted_within_season"] = 1.0

                # Compare values
                for key, exp in expected_combined.items():
                    if key not in student_by_key:
                        base_values_match = False
                        gd_values_match = False
                        roll_gd_match = False
                        roll_sot_match = False
                        roll_pcp_match = False
                        continue
                    r = student_by_key[key]
                    # Base metrics must match input
                    gf = _safe_int(r.get("goals_for", ""))
                    ga = _safe_int(r.get("goals_against", ""))
                    sot = _safe_int(r.get("shots_on_target", ""))
                    pcp = _safe_int(r.get("pass_completion_pct", ""))
                    if not (gf == exp["goals_for"] and ga == exp["goals_against"] and sot == exp["shots_on_target"] and pcp == exp["pass_completion_pct"]):
                        base_values_match = False

                    # goal_diff
                    gd_val = _safe_int(r.get("goal_diff", ""))
                    if gd_val is None or gd_val != exp["goal_diff"]:
                        gd_values_match = False

                    # rolling validations: must be blank for first 4 games; else numeric matching within tolerance
                    # rolling5_goal_diff
                    cell = r.get("rolling5_goal_diff", "")
                    if exp["rolling5_goal_diff"] is None:
                        if not _is_blank(cell):
                            roll_gd_match = False
                    else:
                        rf = _safe_float(cell)
                        if rf is None or not _float_equal(rf, exp["rolling5_goal_diff"]):
                            roll_gd_match = False

                    # rolling5_shots_on_target
                    cell = r.get("rolling5_shots_on_target", "")
                    if exp["rolling5_shots_on_target"] is None:
                        if not _is_blank(cell):
                            roll_sot_match = False
                    else:
                        rf = _safe_float(cell)
                        if rf is None or not _float_equal(rf, exp["rolling5_shots_on_target"]):
                            roll_sot_match = False

                    # rolling5_pass_completion_pct
                    cell = r.get("rolling5_pass_completion_pct", "")
                    if exp["rolling5_pass_completion_pct"] is None:
                        if not _is_blank(cell):
                            roll_pcp_match = False
                    else:
                        rf = _safe_float(cell)
                        if rf is None or not _float_equal(rf, exp["rolling5_pass_completion_pct"]):
                            roll_pcp_match = False

                if base_values_match and expected_keys:
                    scores["base_values_correct"] = 1.0
                elif not expected_keys:
                    # No expected rows, consider base values correct vacuously
                    scores["base_values_correct"] = 1.0

                if gd_values_match and expected_keys:
                    scores["goal_diff_values_correct"] = 1.0
                elif not expected_keys:
                    scores["goal_diff_values_correct"] = 1.0

                if roll_gd_match and expected_keys:
                    scores["rolling5_goal_diff_correct"] = 1.0
                elif not expected_keys:
                    scores["rolling5_goal_diff_correct"] = 1.0

                if roll_sot_match and expected_keys:
                    scores["rolling5_shots_on_target_correct"] = 1.0
                elif not expected_keys:
                    scores["rolling5_shots_on_target_correct"] = 1.0

                if roll_pcp_match and expected_keys:
                    scores["rolling5_pass_completion_pct_correct"] = 1.0
                elif not expected_keys:
                    scores["rolling5_pass_completion_pct_correct"] = 1.0
            else:
                # Missing required columns; other checks remain 0.0
                pass

    # Trend summary checks
    trend_path = workspace / "output" / "season_trend_summary.csv"
    if trend_path.exists():
        scores["trend_exists"] = 1.0
        header = _read_csv_header(trend_path)
        expected_trend_header = ["season", "metric", "first_trailing5", "last_trailing5", "delta", "direction"]
        if header is not None and header == expected_trend_header:
            scores["trend_header_correct"] = 1.0

        rows = _read_csv_dicts(trend_path)
        if rows is not None and len(rows) >= 0:
            # Build expected trend summary from inputs
            expected_summary = _expected_trend_summary(expected_combined)
            # Count expected rows
            metrics_list = ["goal_diff", "shots_on_target", "pass_completion_pct"]
            expected_row_count = len(seasons_expected) * len(metrics_list) if seasons_expected else 0
            # Build found map
            found_map: Dict[Tuple[str, str], Dict] = {}
            for r in rows:
                season_str = str(r.get("season", "")).strip()
                metric = str(r.get("metric", "")).strip()
                key = (season_str, metric)
                if season_str != "" and metric != "":
                    found_map[key] = r
            if expected_row_count > 0 and len(found_map) == expected_row_count:
                scores["trend_row_count_correct"] = 1.0
            elif expected_row_count == 0 and len(found_map) == 0:
                scores["trend_row_count_correct"] = 1.0

            # Validate values
            values_ok = True
            directions_ok = True
            # Only check if we have expected data
            for key, exp in expected_summary.items():
                if key not in found_map:
                    values_ok = False
                    directions_ok = False
                    continue
                r = found_map[key]
                f1 = _safe_float(r.get("first_trailing5", ""))
                f2 = _safe_float(r.get("last_trailing5", ""))
                dlt = _safe_float(r.get("delta", ""))
                dirn = str(r.get("direction", "")).strip()
                if f1 is None or f2 is None or dlt is None:
                    values_ok = False
                else:
                    if not (_float_equal(f1, exp["first_trailing5"]) and _float_equal(f2, exp["last_trailing5"]) and _float_equal(dlt, exp["delta"])):
                        values_ok = False
                if dirn != exp["direction"]:
                    directions_ok = False
            if values_ok and len(expected_summary) > 0:
                scores["trend_values_correct"] = 1.0
            elif len(expected_summary) == 0:
                scores["trend_values_correct"] = 1.0
            if directions_ok and len(expected_summary) > 0:
                scores["trend_directions_correct"] = 1.0
            elif len(expected_summary) == 0:
                scores["trend_directions_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()