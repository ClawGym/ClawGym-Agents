import json
import csv
from pathlib import Path
from datetime import datetime, timedelta
import sys
from typing import Any, Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (len(s) >= 2) and ((s[0] == s[-1]) and (s[0] in ("'", '"'))):
        return s[1:-1]
    return s


def _parse_scalar(val: str) -> Any:
    val = val.strip()
    if val == "":
        return None
    # Try int
    try:
        if val.startswith(("0", "-0")) and val not in ("0", "-0"):
            # avoid octal-like confusion; treat as int if strictly digits with optional sign
            int_val = int(val)
            return int_val
        int_val = int(val)
        return int_val
    except Exception:
        pass
    # Try float
    try:
        if any(c in val for c in ".eE"):
            return float(val)
    except Exception:
        pass
    # Strip quotes
    return _strip_quotes(val)


def simple_yaml_load(text: str) -> Dict[str, Any]:
    # Very simple YAML mapping loader supporting nested dicts via indentation and "key: value" scalars.
    # Does not support lists. Designed for the provided config files.
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    last_container_for_indent: Dict[int, Dict[str, Any]] = {-1: root}

    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        # Ignore comments (naively)
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        # Maintain stack based on indentation
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1] if stack else root
        # Parse "key: [value]"
        if ":" not in line:
            # Malformed for our simple parser; skip gracefully
            continue
        before, after = line.lstrip().split(":", 1)
        key = before.strip()
        value = after.strip()
        if value == "":
            # Start of a nested mapping
            new_dict: Dict[str, Any] = {}
            current[key] = new_dict
            stack.append((indent, new_dict))
        else:
            current[key] = _parse_scalar(value)
    return root


def parse_yaml_file(path: Path) -> Optional[Dict[str, Any]]:
    text = safe_read_text(path)
    if text is None:
        return None
    try:
        data = simple_yaml_load(text)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def nearly_equal(a: float, b: float, tol: float = 0.2) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))


def compute_rainfall_metrics(precip_rows: List[Dict[str, str]]) -> Optional[Tuple[float, float, float, int]]:
    try:
        baseline_years = {2020, 2021, 2022}
        recent_years = {2023, 2024}
        months_wanted = {4, 5, 6, 7, 8, 9}
        baseline_vals: List[float] = []
        recent_vals: List[float] = []
        for r in precip_rows:
            y = int(r["year"])
            m = int(r["month"])
            if m not in months_wanted:
                continue
            v = float(r["rainfall_mm"])
            if y in baseline_years:
                baseline_vals.append(v)
            elif y in recent_years:
                recent_vals.append(v)
        if not baseline_vals or not recent_vals:
            return None
        baseline_avg = sum(baseline_vals) / len(baseline_vals)
        recent_avg = sum(recent_vals) / len(recent_vals)
        if baseline_avg == 0:
            return None
        pct_change = (recent_avg - baseline_avg) / baseline_avg * 100.0
        # Determine adjustment points
        adj_points: int
        if pct_change <= -20.0:
            adj_points = 4
        elif -20.0 < pct_change <= -10.0:
            adj_points = 2
        elif pct_change >= 10.0:
            adj_points = -2
        else:
            adj_points = 0
        return (baseline_avg, recent_avg, pct_change, adj_points)
    except Exception:
        return None


def compute_median_last_frost_date(frost_rows: List[Dict[str, str]]) -> Optional[str]:
    try:
        dates: List[datetime] = []
        for r in frost_rows:
            d = datetime.strptime(r["last_spring_frost_date"], "%Y-%m-%d")
            dates.append(d)
        if not dates:
            return None
        dates.sort()
        median_idx = len(dates) // 2
        median_date = dates[median_idx].date()
        return median_date.isoformat()
    except Exception:
        return None


def load_fields(fields_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, Any]]]:
    try:
        out: List[Dict[str, Any]] = []
        for r in fields_rows:
            out.append({
                "field_id": r["field_id"],
                "field_name": r["field_name"],
                "crop_planned": r["crop_planned"],
            })
        return out
    except Exception:
        return None


def daterange_add(date_str: str, days: int) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    d2 = d + timedelta(days=days)
    return d2.isoformat()


def daterange_sub(date_str: str, days: int) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    d2 = d - timedelta(days=days)
    return d2.isoformat()


def compute_expected_field_tasks(fields: List[Dict[str, Any]], crops_cfg: Dict[str, Any], median_frost: str) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    expected: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    cfg_crops = crops_cfg.get("crops", {}) if isinstance(crops_cfg, dict) else {}
    for f in fields:
        crop = f["crop_planned"]
        if crop not in cfg_crops or not isinstance(cfg_crops.get(crop), dict):
            warnings.append(f"Missing crop config for {crop}")
            continue
        crop_cfg = cfg_crops[crop]
        buffer_days = crop_cfg.get("planting_buffer_days_after_last_frost")
        task_durations = crop_cfg.get("task_durations", {})
        try:
            buffer_days = int(buffer_days)
            prep_days = int(task_durations.get("prep_days"))
            planting_days = int(task_durations.get("planting_days"))
            irrigation_setup_days = int(task_durations.get("irrigation_setup_days"))
        except Exception:
            warnings.append(f"Incomplete task durations for {crop}")
            continue
        planting_start = daterange_add(median_frost, buffer_days)
        # planting end = planting_start + planting_days - 1
        planting_end = daterange_add(planting_start, planting_days - 1)
        prep_start = daterange_sub(planting_start, prep_days)
        prep_end = daterange_sub(planting_start, 1)
        irrigation_setup_start = daterange_add(planting_end, 1)
        irrigation_setup_end = daterange_add(irrigation_setup_start, irrigation_setup_days - 1)
        tasks = [
            {"name": "prep", "start_date": prep_start, "end_date": prep_end, "depends_on": []},
            {"name": "plant", "start_date": planting_start, "end_date": planting_end, "depends_on": ["prep"]},
            {"name": "irrigation_setup", "start_date": irrigation_setup_start, "end_date": irrigation_setup_end, "depends_on": ["plant"]},
        ]
        expected[f["field_id"]] = {
            "field_id": f["field_id"],
            "field_name": f["field_name"],
            "crop": crop,
            "tasks": tasks
        }
    return expected, warnings


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "plan_json_exists": 0.0,
        "plan_source_files_include_required": 0.0,
        "plan_rainfall_trend_values": 0.0,
        "plan_rainfall_adjustment_points": 0.0,
        "plan_median_last_frost_date": 0.0,
        "plan_fields_structure": 0.0,
        "plan_tasks_dates_and_dependencies": 0.0,
        "plan_warnings_correct": 0.0,
        "irrigation_backup_exists_and_valid": 0.0,
        "irrigation_thresholds_adjusted": 0.0,
        "irrigation_global_preserved": 0.0,
    }

    # Paths
    precip_path = workspace / "input" / "weather" / "precip_2020_2024.csv"
    frost_path = workspace / "input" / "weather" / "frost_dates.csv"
    fields_csv_path = workspace / "input" / "fields.csv"
    crops_yaml_path = workspace / "config" / "crops.yaml"
    irrig_yaml_path = workspace / "config" / "irrigation.yaml"
    irrig_backup_path = workspace / "config" / "irrigation.yaml.bak"
    plan_json_path = workspace / "output" / "plan.json"

    # Load inputs for expected computations
    precip_rows = safe_load_csv(precip_path) or []
    frost_rows = safe_load_csv(frost_path) or []
    fields_rows = safe_load_csv(fields_csv_path) or []
    crops_cfg = parse_yaml_file(crops_yaml_path) or {}

    rainfall_metrics = None
    if precip_rows:
        rainfall_metrics = compute_rainfall_metrics(precip_rows)

    median_frost = None
    if frost_rows:
        median_frost = compute_median_last_frost_date(frost_rows)

    fields_list = None
    if fields_rows:
        fields_list = load_fields(fields_rows)

    expected_fields_map: Dict[str, Dict[str, Any]] = {}
    expected_warnings_list: List[str] = []
    if fields_list is not None and isinstance(crops_cfg, dict) and median_frost:
        expected_fields_map, warnings_from_cfg = compute_expected_field_tasks(fields_list, crops_cfg, median_frost)
        # Determine missing crops in irrigation config as well for warnings; per spec, missing in configs
        irrig_cfg_for_missing = parse_yaml_file(irrig_yaml_path) or {}
        irrig_crops = set(irrig_cfg_for_missing.get("crops", {}).keys()) if isinstance(irrig_cfg_for_missing, dict) else set()
        cfg_crops_set = set(crops_cfg.get("crops", {}).keys()) if isinstance(crops_cfg, dict) else set()
        missing_in_configs = set()
        for f in fields_list:
            crop = f["crop_planned"]
            if crop not in cfg_crops_set or crop not in irrig_crops:
                missing_in_configs.add(crop)
        if missing_in_configs:
            # Create deterministic warning messages
            warnings_from_cfg = sorted([f"Missing crop config for {crop}" for crop in missing_in_configs])
        expected_warnings_list = warnings_from_cfg
    else:
        expected_fields_map = {}
        expected_warnings_list = []

    # Load produced plan.json
    plan_obj = safe_load_json(plan_json_path)
    if isinstance(plan_obj, dict):
        scores["plan_json_exists"] = 1.0

        # Check source_files includes required list
        required_sources = {
            "input/weather/precip_2020_2024.csv",
            "input/weather/frost_dates.csv",
            "input/fields.csv",
            "config/crops.yaml",
            "config/irrigation.yaml",
        }
        src_ok = False
        if isinstance(plan_obj.get("source_files"), list):
            normalized = set()
            for s in plan_obj["source_files"]:
                if isinstance(s, str):
                    n = s.replace("\\", "/")
                    if n.startswith("./"):
                        n = n[2:]
                    normalized.add(n)
            if required_sources.issubset(normalized):
                src_ok = True
        scores["plan_source_files_include_required"] = 1.0 if src_ok else 0.0

        # Check rainfall_trend values
        rt = plan_obj.get("rainfall_trend")
        rt_ok = False
        rt_adj_ok = False
        if isinstance(rt, dict) and rainfall_metrics is not None:
            baseline_avg, recent_avg, pct_change, adj_points = rainfall_metrics
            baseline_years_ok = rt.get("baseline_years") == [2020, 2021, 2022]
            recent_years_ok = rt.get("recent_years") == [2023, 2024]
            ba = rt.get("baseline_apr_sep_avg_mm")
            ra = rt.get("recent_apr_sep_avg_mm")
            pc = rt.get("percent_change")
            if baseline_years_ok and recent_years_ok and isinstance(ba, (int, float)) and isinstance(ra, (int, float)) and isinstance(pc, (int, float)):
                if nearly_equal(ba, baseline_avg) and nearly_equal(ra, recent_avg) and nearly_equal(pc, pct_change):
                    rt_ok = True
            if isinstance(rt.get("threshold_adjustment_pct_points"), int) and rt.get("threshold_adjustment_pct_points") == adj_points:
                rt_adj_ok = True
        scores["plan_rainfall_trend_values"] = 1.0 if rt_ok else 0.0
        scores["plan_rainfall_adjustment_points"] = 1.0 if rt_adj_ok else 0.0

        # Median frost date check
        mfd_ok = False
        if median_frost is not None and isinstance(plan_obj.get("median_last_frost_date"), str):
            if plan_obj["median_last_frost_date"] == median_frost:
                mfd_ok = True
        scores["plan_median_last_frost_date"] = 1.0 if mfd_ok else 0.0

        # Fields structure and tasks
        fields_ok = False
        tasks_ok = False
        if isinstance(plan_obj.get("fields"), list) and expected_fields_map:
            # Map by field_id
            plan_fields_map: Dict[str, Dict[str, Any]] = {}
            for fld in plan_obj["fields"]:
                if isinstance(fld, dict) and "field_id" in fld:
                    plan_fields_map[str(fld["field_id"])] = fld
            # We expect an entry for each expected field
            structure_good = True
            tasks_good = True
            for fid, exp in expected_fields_map.items():
                got = plan_fields_map.get(fid)
                if not isinstance(got, dict):
                    structure_good = False
                    tasks_good = False
                    break
                if got.get("field_id") != exp["field_id"]:
                    structure_good = False
                if got.get("field_name") != exp["field_name"]:
                    structure_good = False
                if got.get("crop") != exp["crop"]:
                    structure_good = False
                # tasks check
                g_tasks = got.get("tasks")
                if not (isinstance(g_tasks, list) and len(g_tasks) == 3):
                    tasks_good = False
                else:
                    names = [t.get("name") for t in g_tasks if isinstance(t, dict)]
                    if names != ["prep", "plant", "irrigation_setup"]:
                        tasks_good = False
                    else:
                        # Check dates and dependencies
                        for gt, et in zip(g_tasks, exp["tasks"]):
                            if gt.get("start_date") != et["start_date"]:
                                tasks_good = False
                            if gt.get("end_date") != et["end_date"]:
                                tasks_good = False
                            if gt.get("depends_on") != et["depends_on"]:
                                tasks_good = False
            fields_ok = structure_good
            tasks_ok = tasks_good
        scores["plan_fields_structure"] = 1.0 if fields_ok else 0.0
        scores["plan_tasks_dates_and_dependencies"] = 1.0 if tasks_ok else 0.0

        # Warnings
        warnings_ok = False
        if isinstance(plan_obj.get("warnings"), list):
            # If we expected none, require exact empty list
            if not expected_warnings_list:
                warnings_ok = (plan_obj["warnings"] == [])
            else:
                # Each expected missing crop should appear in at least one warning string
                plan_warnings = [w for w in plan_obj["warnings"] if isinstance(w, str)]
                found_all = True
                for exp_warn in expected_warnings_list:
                    # check crop name presence in any warning string
                    crop_name = exp_warn.split()[-1]
                    if not any(crop_name in w for w in plan_warnings):
                        found_all = False
                        break
                warnings_ok = found_all
        scores["plan_warnings_correct"] = 1.0 if warnings_ok else 0.0

    # Irrigation backup exists and valid
    backup_cfg = parse_yaml_file(irrig_backup_path)
    if isinstance(backup_cfg, dict) and "crops" in backup_cfg and isinstance(backup_cfg["crops"], dict):
        # Verify that each crop has moisture_trigger_pct
        crops_ok = True
        for c, v in backup_cfg["crops"].items():
            if not (isinstance(v, dict) and "moisture_trigger_pct" in v and isinstance(v["moisture_trigger_pct"], (int, float))):
                crops_ok = False
                break
        if crops_ok:
            scores["irrigation_backup_exists_and_valid"] = 1.0

    # Irrigation thresholds adjusted correctness
    current_irrig_cfg = parse_yaml_file(irrig_yaml_path)
    thresholds_ok = False
    global_preserved_ok = False
    if isinstance(backup_cfg, dict) and isinstance(current_irrig_cfg, dict) and rainfall_metrics is not None:
        _, _, _, adj_points = rainfall_metrics
        backup_crops = backup_cfg.get("crops", {}) if isinstance(backup_cfg.get("crops"), dict) else {}
        current_crops = current_irrig_cfg.get("crops", {}) if isinstance(current_irrig_cfg.get("crops"), dict) else {}
        if backup_crops and current_crops:
            all_match = True
            for crop, bvals in backup_crops.items():
                if not isinstance(bvals, dict) or "moisture_trigger_pct" not in bvals:
                    all_match = False
                    break
                b = bvals["moisture_trigger_pct"]
                try:
                    b_int = int(b)
                except Exception:
                    all_match = False
                    break
                expected_new = clamp(b_int + adj_points, 10, 35)
                cvals = current_crops.get(crop)
                if not isinstance(cvals, dict) or "moisture_trigger_pct" not in cvals:
                    all_match = False
                    break
                try:
                    c_int = int(cvals["moisture_trigger_pct"])
                except Exception:
                    all_match = False
                    break
                if c_int != expected_new:
                    all_match = False
                    break
                # Ensure within caps
                if not (10 <= c_int <= 35):
                    all_match = False
                    break
            thresholds_ok = all_match
        # Global preserved
        b_global = backup_cfg.get("global")
        c_global = current_irrig_cfg.get("global")
        if b_global == c_global:
            global_preserved_ok = True
    scores["irrigation_thresholds_adjusted"] = 1.0 if thresholds_ok else 0.0
    scores["irrigation_global_preserved"] = 1.0 if global_preserved_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()