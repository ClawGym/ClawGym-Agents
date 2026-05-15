import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any


def read_csv_rows(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames
    except Exception:
        return None, None


def read_json_file(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_yaml_thresholds(path: Path) -> Optional[Dict[str, float]]:
    """
    Minimal parser for used_config.yaml focusing on:
    risk_thresholds:
      KEY: float
      ...
    Returns dict of thresholds or None on failure.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = text.splitlines()
    thresholds: Dict[str, float] = {}
    block_indent = None
    in_block = False
    for line in lines:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not in_block:
            stripped = line.lstrip()
            if stripped.startswith("risk_thresholds:"):
                block_indent = len(line) - len(stripped)
                in_block = True
            continue
        else:
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= (block_indent or 0):
                break
            m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*([0-9]*\.?[0-9]+)\s*$", line)
            if m:
                key = m.group(1).strip()
                try:
                    val = float(m.group(2))
                except Exception:
                    return None
                thresholds[key] = val
    if not thresholds:
        return None
    return thresholds


def round4(x: float) -> float:
    return round(x, 4)


def parse_float_str(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def normalize_platform_list(s: str) -> List[str]:
    if s is None:
        return []
    s = s.strip()
    if not s:
        return []
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return parts


def compute_expected_aggregates(workspace: Path) -> Optional[Dict[str, Any]]:
    suppliers_csv = workspace / "input" / "suppliers.csv"
    parts_csv = workspace / "input" / "parts.csv"
    monthly_dir = workspace / "input" / "failures" / "monthly"

    suppliers_rows, _ = read_csv_rows(suppliers_csv)
    parts_rows, _ = read_csv_rows(parts_csv)

    if suppliers_rows is None or parts_rows is None:
        return None

    supplier_name_by_id: Dict[str, str] = {}
    for r in suppliers_rows:
        sid = r.get("supplier_id")
        sname = r.get("supplier_name")
        if sid is None or sname is None:
            return None
        supplier_name_by_id[sid] = sname

    part_to_supplier: Dict[str, str] = {}
    part_to_platform: Dict[str, str] = {}
    for r in parts_rows:
        pn = r.get("part_number")
        plat = r.get("platform")
        sid = r.get("supplier_id")
        if pn is None or plat is None or sid is None:
            return None
        part_to_supplier[pn] = sid
        part_to_platform[pn] = plat

    if not monthly_dir.exists():
        return None
    monthly_files = sorted([p for p in monthly_dir.glob("*.csv") if p.is_file()])
    if not monthly_files:
        return {
            "supplier_name_by_id": supplier_name_by_id,
            "expected_thresholds": {"MBT": 0.02, "APC": 0.03, "UAV": 0.04, "ARTY": 0.05},
            "supplier_totals": {},
            "supplier_platform_totals": {},
            "platform_totals": {},
            "monthly_files": monthly_files,
            "monthly_counts": {}
        }

    monthly_counts: Dict[str, int] = {}
    all_rows: List[Dict[str, str]] = []
    for mf in monthly_files:
        rows, _ = read_csv_rows(mf)
        if rows is None:
            return None
        monthly_counts[mf.as_posix()] = len(rows)
        all_rows.extend(rows)

    supplier_totals: Dict[str, Dict[str, int]] = {}
    supplier_platform_totals: Dict[str, Dict[str, Dict[str, int]]] = {}
    platform_totals: Dict[str, Dict[str, int]] = {}

    for r in all_rows:
        pn = r.get("part_number")
        if pn not in part_to_supplier or pn not in part_to_platform:
            return None
        sid = part_to_supplier[pn]
        plat = part_to_platform[pn]
        try:
            shipped = int(r.get("shipped_qty", "0"))
            failed = int(r.get("failure_qty", "0"))
        except Exception:
            return None

        supplier_totals.setdefault(sid, {"total_shipped": 0, "total_failures": 0})
        supplier_totals[sid]["total_shipped"] += shipped
        supplier_totals[sid]["total_failures"] += failed

        supplier_platform_totals.setdefault(sid, {})
        supplier_platform_totals[sid].setdefault(plat, {"shipped": 0, "failures": 0})
        supplier_platform_totals[sid][plat]["shipped"] += shipped
        supplier_platform_totals[sid][plat]["failures"] += failed

        platform_totals.setdefault(plat, {"total_shipped": 0, "total_failures": 0})
        platform_totals[plat]["total_shipped"] += shipped
        platform_totals[plat]["total_failures"] += failed

    expected_thresholds = {"MBT": 0.02, "APC": 0.03, "UAV": 0.04, "ARTY": 0.05}

    return {
        "supplier_name_by_id": supplier_name_by_id,
        "expected_thresholds": expected_thresholds,
        "supplier_totals": supplier_totals,
        "supplier_platform_totals": supplier_platform_totals,
        "platform_totals": platform_totals,
        "monthly_files": monthly_files,
        "monthly_counts": monthly_counts
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "risk_summary_columns_and_suppliers": 0.0,
        "risk_summary_values_correct": 0.0,
        "platform_breakdown_values_correct": 0.0,
        "manifest_covers_monthly_files": 0.0,
        "used_config_thresholds_present": 0.0,
        "breakdown_thresholds_match_used_config": 0.0,
    }

    exp = compute_expected_aggregates(workspace)

    # Check manifest
    manifest_path = workspace / "output" / "manifest.json"
    manifest = read_json_file(manifest_path)
    monthly_dir = workspace / "input" / "failures" / "monthly"
    expected_monthly_files = sorted([p for p in monthly_dir.glob("*.csv") if p.is_file()]) if monthly_dir.exists() else []
    if expected_monthly_files:
        if isinstance(manifest, list):
            manifest_map: Dict[str, int] = {}
            valid = True
            for item in manifest:
                if not isinstance(item, dict):
                    valid = False
                    break
                fp = item.get("file_path")
                rc = item.get("row_count")
                if not isinstance(fp, str) or not isinstance(rc, int):
                    valid = False
                    break
                if fp in manifest_map:
                    valid = False
                    break
                manifest_map[fp] = rc
            if valid:
                expected_paths = [p.as_posix() for p in expected_monthly_files]
                if set(manifest_map.keys()) == set(expected_paths):
                    counts_ok = True
                    for p in expected_monthly_files:
                        rows, _ = read_csv_rows(p)
                        if rows is None:
                            counts_ok = False
                            break
                        if manifest_map.get(p.as_posix()) != len(rows):
                            counts_ok = False
                            break
                    if counts_ok:
                        scores["manifest_covers_monthly_files"] = 1.0
    else:
        if isinstance(manifest, list) and len(manifest) == 0:
            scores["manifest_covers_monthly_files"] = 1.0

    # used_config thresholds present
    used_config_path = workspace / "output" / "used_config.yaml"
    used_thresholds = None
    if used_config_path.exists():
        used_thresholds = parse_yaml_thresholds(used_config_path)
        if used_thresholds is not None:
            expected_thresh = {"MBT": 0.02, "APC": 0.03, "UAV": 0.04, "ARTY": 0.05}
            required_ok = True
            for k, v in expected_thresh.items():
                if k not in used_thresholds:
                    required_ok = False
                    break
                if round4(float(used_thresholds[k])) != round4(v):
                    required_ok = False
                    break
            if required_ok:
                scores["used_config_thresholds_present"] = 1.0

    # risk_summary checks
    rs_path = workspace / "output" / "risk_summary.csv"
    rs_rows, rs_fields = read_csv_rows(rs_path) if rs_path.exists() else (None, None)
    if exp is not None and rs_rows is not None and rs_fields is not None:
        expected_columns = ["supplier_id", "supplier_name", "total_shipped", "total_failures", "failure_rate", "risk_flag", "high_risk_platforms"]
        cols_ok = rs_fields == expected_columns
        suppliers_list = list(exp["supplier_name_by_id"].keys())
        rs_supplier_ids = [r.get("supplier_id") for r in rs_rows]
        supplier_set_ok = set(rs_supplier_ids) == set(suppliers_list) and len(rs_rows) == len(suppliers_list) and None not in rs_supplier_ids
        if cols_ok and supplier_set_ok:
            scores["risk_summary_columns_and_suppliers"] = 1.0

        supplier_totals = exp["supplier_totals"]
        supplier_platform_totals = exp["supplier_platform_totals"]
        expected_thresh = exp["expected_thresholds"]
        rs_by_sid = {r["supplier_id"]: r for r in rs_rows if r.get("supplier_id") is not None}
        total_checks = 0
        correct_checks = 0
        for sid, sname in exp["supplier_name_by_id"].items():
            total_checks += 1
            row = rs_by_sid.get(sid)
            if row is None:
                continue
            t_ship = supplier_totals.get(sid, {}).get("total_shipped", 0)
            t_fail = supplier_totals.get(sid, {}).get("total_failures", 0)
            exp_rate = round4((t_fail / t_ship) if t_ship > 0 else 0.0)

            high_plats: List[str] = []
            plat_map = supplier_platform_totals.get(sid, {})
            for plat, agg in plat_map.items():
                s = agg.get("shipped", 0)
                f = agg.get("failures", 0)
                rate = (f / s) if s > 0 else 0.0
                thr = expected_thresh.get(plat)
                if thr is not None and rate > thr:
                    high_plats.append(plat)
            high_plats_sorted = sorted(high_plats)
            exp_flag = "HIGH" if high_plats_sorted else "OK"

            try:
                row_ship = int(row.get("total_shipped", ""))
                row_fail = int(row.get("total_failures", ""))
            except Exception:
                continue
            rate_str = row.get("failure_rate")
            rate_val = parse_float_str(rate_str) if rate_str is not None else None
            row_flag = row.get("risk_flag")
            row_plats = normalize_platform_list(row.get("high_risk_platforms", ""))

            if row.get("supplier_name") != sname:
                continue
            if row_ship != t_ship or row_fail != t_fail:
                continue
            if rate_val is None or round4(rate_val) != exp_rate:
                continue
            if sorted(row_plats) != high_plats_sorted:
                continue
            if row_flag != exp_flag:
                continue
            correct_checks += 1

        if total_checks > 0:
            scores["risk_summary_values_correct"] = correct_checks / total_checks

    # platform_breakdown checks
    pb_path = workspace / "output" / "platform_breakdown.json"
    pb = read_json_file(pb_path) if pb_path.exists() else None
    if exp is not None and isinstance(pb, dict):
        platform_totals = exp["platform_totals"]
        expected_thresh = exp["expected_thresholds"]
        expected_platforms = set(platform_totals.keys()) | set(expected_thresh.keys())
        if set(pb.keys()) == expected_platforms:
            total_checks = 0
            correct_checks = 0
            for plat in sorted(expected_platforms):
                total_checks += 1
                entry = pb.get(plat)
                if not isinstance(entry, dict):
                    continue
                agg = platform_totals.get(plat, {"total_shipped": 0, "total_failures": 0})
                t_ship = agg.get("total_shipped", 0)
                t_fail = agg.get("total_failures", 0)
                exp_rate = round4((t_fail / t_ship) if t_ship > 0 else 0.0)
                exp_thr = expected_thresh.get(plat)
                js_ship = entry.get("total_shipped")
                js_fail = entry.get("total_failures")
                js_rate = entry.get("failure_rate")
                js_thr = entry.get("threshold_used")
                try:
                    js_ship_i = int(js_ship)
                    js_fail_i = int(js_fail)
                except Exception:
                    continue
                try:
                    js_rate_f = float(js_rate)
                except Exception:
                    continue
                try:
                    js_thr_f = float(js_thr)
                except Exception:
                    continue
                if js_ship_i != t_ship or js_fail_i != t_fail:
                    continue
                if round4(js_rate_f) != exp_rate:
                    continue
                if exp_thr is None or round4(js_thr_f) != round4(exp_thr):
                    continue
                correct_checks += 1
            if total_checks > 0:
                scores["platform_breakdown_values_correct"] = correct_checks / total_checks

    # breakdown thresholds match used_config cross-check (both directions)
    if isinstance(pb, dict) and used_thresholds is not None:
        ok = True
        # pb -> used_config
        for plat, entry in pb.items():
            if not isinstance(entry, dict):
                ok = False
                break
            js_thr = entry.get("threshold_used")
            try:
                js_thr_f = float(js_thr)
            except Exception:
                ok = False
                break
            if plat not in used_thresholds:
                ok = False
                break
            if round4(js_thr_f) != round4(float(used_thresholds[plat])):
                ok = False
                break
        # used_config -> pb
        if ok:
            for plat, thr in used_thresholds.items():
                if plat not in pb or not isinstance(pb[plat], dict):
                    ok = False
                    break
                try:
                    pb_thr = float(pb[plat].get("threshold_used"))
                except Exception:
                    ok = False
                    break
                if round4(pb_thr) != round4(float(thr)):
                    ok = False
                    break
        if ok:
            scores["breakdown_thresholds_match_used_config"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()