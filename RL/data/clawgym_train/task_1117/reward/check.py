import sys
import json
import csv
from pathlib import Path
from datetime import date
from typing import List, Dict, Any, Optional


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _read_jsonl_objects(path: Path) -> Optional[List[Dict[str, Any]]]:
    objs = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                objs.append(json.loads(line))
        return objs
    except Exception:
        return None


def _list_voyage_csvs(dir_path: Path) -> Optional[List[Path]]:
    try:
        if not dir_path.exists() or not dir_path.is_dir():
            return None
        csvs = sorted([p for p in dir_path.iterdir() if p.is_file() and p.suffix.lower() == ".csv"])
        return csvs
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _nearly_equal(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) <= tol


def _to_float(s: Any) -> Optional[float]:
    try:
        if isinstance(s, (int, float)):
            return float(s)
        return float(str(s).strip())
    except Exception:
        return None


def _normalize_rel_path_str(s: str) -> str:
    s = s.strip().replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    while s.startswith("/"):
        s = s[1:]
    return s


def _compute_expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    port_info_path = workspace / "input" / "port_info.csv"
    voyage_logs_dir = workspace / "input" / "voyage_logs"
    manifests_path = workspace / "input" / "manifests.jsonl"

    if not port_info_path.exists() or not manifests_path.exists():
        return None
    csvs = _list_voyage_csvs(voyage_logs_dir)
    if csvs is None:
        return None

    port_rows = _read_csv_rows(port_info_path)
    if port_rows is None:
        return None
    port_map: Dict[str, Dict[str, str]] = {}
    for row in port_rows:
        code = row.get("port_code")
        name = row.get("port_name")
        region = row.get("region")
        if code is None or name is None or region is None:
            return None
        port_map[code] = {"port_name": name, "region": region}

    all_logs: List[Dict[str, Any]] = []
    for p in csvs:
        rows = _read_csv_rows(p)
        if rows is None:
            return None
        for r in rows:
            for key in ["voyage_id", "port_code", "departure_date", "arrival_date", "scheduled_arrival_date", "reported_delivered_tonnage"]:
                if key not in r or r[key] == "":
                    return None
            dep = _parse_date(r["departure_date"])
            arr = _parse_date(r["arrival_date"])
            sched = _parse_date(r["scheduled_arrival_date"])
            rep = _to_float(r["reported_delivered_tonnage"])
            if dep is None or arr is None or sched is None or rep is None:
                return None
            on_time = arr <= sched
            transit_days = (arr - dep).days
            all_logs.append({
                "voyage_id": r["voyage_id"],
                "port_code": r["port_code"],
                "departure_date": dep,
                "arrival_date": arr,
                "scheduled_arrival_date": sched,
                "reported_delivered_tonnage": rep,
                "on_time": on_time,
                "transit_days": float(transit_days),
            })

    per_port: Dict[str, Dict[str, Any]] = {}
    for log in all_logs:
        pc = log["port_code"]
        if pc not in per_port:
            per_port[pc] = {
                "voyages_count": 0,
                "on_time_count": 0,
                "total_delivered_tonnage": 0.0,
                "sum_transit_days": 0.0,
            }
        agg = per_port[pc]
        agg["voyages_count"] += 1
        if log["on_time"]:
            agg["on_time_count"] += 1
        agg["total_delivered_tonnage"] += float(log["reported_delivered_tonnage"])
        agg["sum_transit_days"] += float(log["transit_days"])

    for pc, agg in per_port.items():
        vc = agg["voyages_count"]
        avg_transit = agg["sum_transit_days"] / vc if vc > 0 else 0.0
        agg["avg_transit_days"] = avg_transit

    overall = {
        "voyages_count": sum(agg["voyages_count"] for agg in per_port.values()),
        "on_time_count": sum(agg["on_time_count"] for agg in per_port.values()),
        "total_delivered_tonnage": sum(agg["total_delivered_tonnage"] for agg in per_port.values()),
        "sum_transit_days": sum(agg["sum_transit_days"] for agg in per_port.values()),
    }
    overall["avg_transit_days"] = (overall["sum_transit_days"] / overall["voyages_count"]) if overall["voyages_count"] > 0 else 0.0

    expected_processed = [str(p.relative_to(workspace).as_posix()) for p in csvs]

    manifest_objs = _read_jsonl_objects(manifests_path)
    if manifest_objs is None:
        return None
    manifest_sums: Dict[str, float] = {}
    for obj in manifest_objs:
        vid = obj.get("voyage_id")
        cargo = obj.get("cargo")
        if not isinstance(vid, str) or not isinstance(cargo, list):
            return None
        total = 0.0
        for item in cargo:
            wt = item.get("weight_tons")
            wt_f = _to_float(wt)
            if wt_f is None:
                return None
            total += wt_f
        manifest_sums[vid] = total

    logs_by_vid: Dict[str, Dict[str, Any]] = {l["voyage_id"]: l for l in all_logs}
    tolerance = 0.1
    mismatches_expected: List[Dict[str, Any]] = []
    for vid, log in logs_by_vid.items():
        if vid in manifest_sums:
            reported = float(log["reported_delivered_tonnage"])
            manifest_sum = float(manifest_sums[vid])
            diff = manifest_sum - reported
            if abs(diff) > tolerance:
                mismatches_expected.append({
                    "voyage_id": vid,
                    "port_code": log["port_code"],
                    "reported_delivered_tonnage": reported,
                    "manifest_sum_tonnage": manifest_sum,
                    "difference_tons": diff,
                })

    return {
        "port_map": port_map,
        "logs": all_logs,
        "per_port": per_port,
        "overall": overall,
        "expected_processed_files": expected_processed,
        "manifest_sums": manifest_sums,
        "mismatches_expected": mismatches_expected,
        "tolerance": 0.1,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "processed_files_exists": 0.0,
        "processed_files_content_match": 0.0,
        "quarterly_summary_exists": 0.0,
        "quarterly_summary_header_correct": 0.0,
        "quarterly_summary_row_count": 0.0,
        "per_port_values_correct": 0.0,
        "overall_row_correct": 0.0,
        "consistency_checks_exists": 0.0,
        "consistency_tolerance_value": 0.0,
        "consistency_mismatch_set_correct": 0.0,
        "consistency_mismatch_details_correct": 0.0,
    }

    expected = _compute_expected_from_inputs(workspace)

    processed_path = workspace / "output" / "processed_files.txt"
    if processed_path.exists():
        scores["processed_files_exists"] = 1.0
        if expected is not None:
            try:
                content_lines = []
                with processed_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if s != "":
                            content_lines.append(_normalize_rel_path_str(s))
                expected_set = set(_normalize_rel_path_str(p) for p in expected["expected_processed_files"])
                got_set = set(content_lines)
                if expected_set == got_set:
                    scores["processed_files_content_match"] = 1.0
            except Exception:
                pass

    summary_path = workspace / "output" / "quarterly_summary.csv"
    if summary_path.exists():
        scores["quarterly_summary_exists"] = 1.0
        rows = None
        try:
            with summary_path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames
                expected_header = [
                    "port_code",
                    "port_name",
                    "region",
                    "voyages_count",
                    "on_time_count",
                    "total_delivered_tonnage",
                    "avg_transit_days",
                ]
                if header == expected_header:
                    scores["quarterly_summary_header_correct"] = 1.0
                rows = [dict(r) for r in reader]
        except Exception:
            rows = None
        if rows is not None and expected is not None:
            by_pc: Dict[str, Dict[str, str]] = {}
            duplicate = False
            for r in rows:
                pc = r.get("port_code")
                if pc is None:
                    duplicate = True
                    break
                if pc in by_pc:
                    duplicate = True
                by_pc[pc] = r
            if not duplicate:
                expected_ports = set(expected["per_port"].keys())
                if set(by_pc.keys()) == expected_ports.union({"ALL"}):
                    scores["quarterly_summary_row_count"] = 1.0
                per_port_ok = True
                for pc, agg in expected["per_port"].items():
                    r = by_pc.get(pc)
                    if r is None:
                        per_port_ok = False
                        break
                    pm = expected["port_map"].get(pc)
                    if pm is None:
                        per_port_ok = False
                        break
                    if (r.get("port_name") or "").strip() != pm["port_name"]:
                        per_port_ok = False
                        break
                    if (r.get("region") or "").strip() != pm["region"]:
                        per_port_ok = False
                        break
                    vc = _to_float(r.get("voyages_count"))
                    oc = _to_float(r.get("on_time_count"))
                    tot = _to_float(r.get("total_delivered_tonnage"))
                    avg = _to_float(r.get("avg_transit_days"))
                    if None in (vc, oc, tot, avg):
                        per_port_ok = False
                        break
                    if not _nearly_equal(vc, float(agg["voyages_count"]), tol=1e-6):
                        per_port_ok = False
                        break
                    if not _nearly_equal(oc, float(agg["on_time_count"]), tol=1e-6):
                        per_port_ok = False
                        break
                    if not _nearly_equal(tot, float(agg["total_delivered_tonnage"]), tol=1e-3):
                        per_port_ok = False
                        break
                    if not _nearly_equal(avg, float(agg["avg_transit_days"]), tol=1e-3):
                        per_port_ok = False
                        break
                if per_port_ok:
                    scores["per_port_values_correct"] = 1.0
                overall_ok = True
                overall_row = by_pc.get("ALL")
                if overall_row is None:
                    overall_ok = False
                else:
                    if (overall_row.get("port_name") or "").strip() != "ALL_PORTS":
                        overall_ok = False
                    if (overall_row.get("region") or "").strip() != "ALL_REGIONS":
                        overall_ok = False
                    vc = _to_float(overall_row.get("voyages_count"))
                    oc = _to_float(overall_row.get("on_time_count"))
                    tot = _to_float(overall_row.get("total_delivered_tonnage"))
                    avg = _to_float(overall_row.get("avg_transit_days"))
                    if None in (vc, oc, tot, avg):
                        overall_ok = False
                    else:
                        exp_overall = expected["overall"]
                        if not _nearly_equal(vc, float(exp_overall["voyages_count"]), tol=1e-6):
                            overall_ok = False
                        if not _nearly_equal(oc, float(exp_overall["on_time_count"]), tol=1e-6):
                            overall_ok = False
                        if not _nearly_equal(tot, float(exp_overall["total_delivered_tonnage"]), tol=1e-3):
                            overall_ok = False
                        if not _nearly_equal(avg, float(exp_overall["avg_transit_days"]), tol=1e-3):
                            overall_ok = False
                if overall_ok:
                    scores["overall_row_correct"] = 1.0

    consistency_path = workspace / "output" / "consistency_checks.json"
    if consistency_path.exists():
        scores["consistency_checks_exists"] = 1.0
        data = None
        try:
            with consistency_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
        if data is not None and expected is not None:
            tol_val = data.get("tolerance_tons", None)
            if isinstance(tol_val, (int, float)) and _nearly_equal(float(tol_val), expected["tolerance"], tol=1e-9):
                scores["consistency_tolerance_value"] = 1.0
            mismatches = data.get("mismatches", None)
            if isinstance(mismatches, list):
                expected_mismatches = expected["mismatches_expected"]
                exp_by_vid = {m["voyage_id"]: m for m in expected_mismatches}
                got_by_vid = {}
                set_ok = True
                for m in mismatches:
                    vid = m.get("voyage_id")
                    if not isinstance(vid, str):
                        set_ok = False
                        break
                    got_by_vid[vid] = m
                if set(got_by_vid.keys()) == set(exp_by_vid.keys()) and set_ok:
                    scores["consistency_mismatch_set_correct"] = 1.0
                    details_ok = True
                    for vid, exp in exp_by_vid.items():
                        gm = got_by_vid.get(vid)
                        if gm is None:
                            details_ok = False
                            break
                        if gm.get("port_code") != exp["port_code"]:
                            details_ok = False
                            break
                        g_rep = _to_float(gm.get("reported_delivered_tonnage"))
                        g_man = _to_float(gm.get("manifest_sum_tonnage"))
                        g_diff = _to_float(gm.get("difference_tons"))
                        if None in (g_rep, g_man, g_diff):
                            details_ok = False
                            break
                        if not _nearly_equal(g_rep, float(exp["reported_delivered_tonnage"]), tol=1e-6):
                            details_ok = False
                            break
                        if not _nearly_equal(g_man, float(exp["manifest_sum_tonnage"]), tol=1e-6):
                            details_ok = False
                            break
                        if not _nearly_equal(g_diff, float(exp["difference_tons"]), tol=1e-6):
                            details_ok = False
                            break
                    if details_ok:
                        scores["consistency_mismatch_details_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()