import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

def num(x):
    return isinstance(x, (int, float))

def approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def list_snapshot_files(snap_dir: str) -> List[str]:
    if not os.path.isdir(snap_dir):
        return []
    files = []
    for name in os.listdir(snap_dir):
        if name.lower().endswith(".json"):
            files.append(os.path.join(snap_dir, name))
    return sorted(files)

def get_date_from_snapshot(path: str, data: Dict[str, Any]) -> Optional[str]:
    # Prefer "date" field; fallback to filename stem if it looks like YYYY-MM-DD
    if isinstance(data, dict):
        d = data.get("date")
        if isinstance(d, str) and d.strip():
            return d.strip()
    base = os.path.basename(path)
    stem = base[:-5] if base.lower().endswith(".json") else base
    # Minimal sanity: length 10 with dashes at positions 4 and 7
    if len(stem) == 10 and stem[4] == "-" and stem[7] == "-":
        return stem
    return None

def safe_get(d: Dict[str, Any], *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def compute_expected_from_inputs(input_dir: str) -> Dict[str, Any]:
    snap_dir = os.path.join(input_dir, "snapshots")
    files = list_snapshot_files(snap_dir)
    snapshots: List[Tuple[str, Dict[str, Any]]] = []
    for p in files:
        data = read_json(p)
        if isinstance(data, dict):
            date = get_date_from_snapshot(p, data)
            if date is None:
                # If no date, use filename order but keep as None to exclude from period calc
                date = ""
            snapshots.append((date, data))

    # Sort by date ascending (empty dates first)
    snapshots.sort(key=lambda t: t[0])

    dates = [d for d, _ in snapshots if isinstance(d, str) and d]
    unique_dates = sorted(set(dates))
    period_start = unique_dates[0] if unique_dates else None
    period_end = unique_dates[-1] if unique_dates else None
    period_days = len(unique_dates)

    # Latest snapshot by date (use last with non-empty date; if none, last overall)
    latest_idx = None
    for i in range(len(snapshots) - 1, -1, -1):
        if snapshots[i][0]:
            latest_idx = i
            break
    if latest_idx is None and snapshots:
        latest_idx = len(snapshots) - 1

    bm25_hit_rates: List[float] = []
    bm25_avg_scores: List[float] = []
    file_counts: List[float] = []
    chunk_counts: List[float] = []
    gw_qmd_errors: List[float] = []
    gw_session_saves_total = 0.0
    gw_qmd_armed_total = 0.0

    for _, snap in snapshots:
        hr = safe_get(snap, "bm25", "hit_rate")
        if num(hr):
            bm25_hit_rates.append(float(hr))
        ascore = safe_get(snap, "bm25", "avg_score")
        if num(ascore):
            bm25_avg_scores.append(float(ascore))

        fc = safe_get(snap, "index", "file_count")
        if num(fc):
            file_counts.append(float(fc))
        cc = safe_get(snap, "index", "chunk_count")
        if num(cc):
            chunk_counts.append(float(cc))

        qe = safe_get(snap, "gateway", "qmd_errors")
        if num(qe):
            gw_qmd_errors.append(float(qe))

        ss = safe_get(snap, "gateway", "session_saves")
        if num(ss):
            gw_session_saves_total += float(ss)
        qa = safe_get(snap, "gateway", "qmd_armed")
        if num(qa):
            gw_qmd_armed_total += float(qa)

    def agg_min(vals: List[float]) -> Optional[float]:
        return min(vals) if vals else None

    def agg_max(vals: List[float]) -> Optional[float]:
        return max(vals) if vals else None

    def agg_avg(vals: List[float]) -> Optional[float]:
        return (sum(vals) / len(vals)) if vals else None

    latest_file_count = None
    latest_chunk_count = None
    if latest_idx is not None:
        latest_snap = snapshots[latest_idx][1]
        lfc = safe_get(latest_snap, "index", "file_count")
        if num(lfc):
            latest_file_count = float(lfc)
        lcc = safe_get(latest_snap, "index", "chunk_count")
        if num(lcc):
            latest_chunk_count = float(lcc)

    return {
        "snap_count": len(files),
        "period_start": period_start,
        "period_end": period_end,
        "period_days": period_days,
        "bm25_hit_rate": {
            "min": agg_min(bm25_hit_rates),
            "max": agg_max(bm25_hit_rates),
            "avg": agg_avg(bm25_hit_rates),
        },
        "bm25_avg_score": {
            "min": agg_min(bm25_avg_scores),
            "max": agg_max(bm25_avg_scores),
            "avg": agg_avg(bm25_avg_scores),
        },
        "index_file_count": {
            "min": agg_min(file_counts),
            "max": agg_max(file_counts),
            "last": latest_file_count,
        },
        "index_chunk_count": {
            "min": agg_min(chunk_counts),
            "max": agg_max(chunk_counts),
            "last": latest_chunk_count,
        },
        "gateway": {
            "qmd_errors_total": sum(gw_qmd_errors) if gw_qmd_errors else 0.0,
            "qmd_errors_max_daily": max(gw_qmd_errors) if gw_qmd_errors else 0.0,
            "session_saves_total": gw_session_saves_total,
            "qmd_armed_total": gw_qmd_armed_total,
        },
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    telemetry_dir = os.path.join(output_dir, "telemetry")

    checks: Dict[str, bool] = {
        "has_summary_file": False,
        "summary_schema_valid": False,
        "summary_period_values_valid": False,
        "summary_bm25_values_correct": False,
        "summary_index_values_correct": False,
        "summary_gateway_values_correct": False,
        "has_trend_file": False,
        "trend_header_ok": False,
        "trend_min_rows": False,
        "has_anomalies_file": False,
        "anomalies_schema_valid": False,
        "has_recommendations_file": False,
        "recommendations_min_lines": False,
        "recommendations_contains_keywords": False,
    }

    # Expected values from input snapshots (reference)
    expected = compute_expected_from_inputs(input_dir)

    # 1) summary.json
    summary_path = os.path.join(telemetry_dir, "summary.json")
    summary = read_json(summary_path) if os.path.isfile(summary_path) else None
    if isinstance(summary, dict):
        checks["has_summary_file"] = True

        # Schema presence and types
        period = summary.get("period", {})
        counts = summary.get("counts", {})
        bm25 = summary.get("bm25", {})
        index = summary.get("index", {})
        gateway = summary.get("gateway", {})

        required = [
            ("period.start", isinstance(period.get("start"), str)),
            ("period.end", isinstance(period.get("end"), str)),
            ("period.days", num(period.get("days"))),
            ("counts.snapshots", num(counts.get("snapshots"))),
            ("bm25.hit_rate.min", num(bm25.get("hit_rate", {}).get("min")) if isinstance(bm25.get("hit_rate"), dict) else False),
            ("bm25.hit_rate.max", num(bm25.get("hit_rate", {}).get("max")) if isinstance(bm25.get("hit_rate"), dict) else False),
            ("bm25.hit_rate.avg", num(bm25.get("hit_rate", {}).get("avg")) if isinstance(bm25.get("hit_rate"), dict) else False),
            ("bm25.avg_score.min", num(bm25.get("avg_score", {}).get("min")) if isinstance(bm25.get("avg_score"), dict) else False),
            ("bm25.avg_score.max", num(bm25.get("avg_score", {}).get("max")) if isinstance(bm25.get("avg_score"), dict) else False),
            ("bm25.avg_score.avg", num(bm25.get("avg_score", {}).get("avg")) if isinstance(bm25.get("avg_score"), dict) else False),
            ("index.file_count.min", num(index.get("file_count", {}).get("min")) if isinstance(index.get("file_count"), dict) else False),
            ("index.file_count.max", num(index.get("file_count", {}).get("max")) if isinstance(index.get("file_count"), dict) else False),
            ("index.file_count.last", num(index.get("file_count", {}).get("last")) if isinstance(index.get("file_count"), dict) else False),
            ("index.chunk_count.min", num(index.get("chunk_count", {}).get("min")) if isinstance(index.get("chunk_count"), dict) else False),
            ("index.chunk_count.max", num(index.get("chunk_count", {}).get("max")) if isinstance(index.get("chunk_count"), dict) else False),
            ("index.chunk_count.last", num(index.get("chunk_count", {}).get("last")) if isinstance(index.get("chunk_count"), dict) else False),
            ("gateway.qmd_errors.total", num(gateway.get("qmd_errors", {}).get("total")) if isinstance(gateway.get("qmd_errors"), dict) else False),
            ("gateway.qmd_errors.max_daily", num(gateway.get("qmd_errors", {}).get("max_daily")) if isinstance(gateway.get("qmd_errors"), dict) else False),
            ("gateway.session_saves.total", num(gateway.get("session_saves", {}).get("total")) if isinstance(gateway.get("session_saves"), dict) else False),
            ("gateway.qmd_armed.total", num(gateway.get("qmd_armed", {}).get("total")) if isinstance(gateway.get("qmd_armed"), dict) else False),
        ]
        schema_ok = all(flag for _, flag in required)
        checks["summary_schema_valid"] = schema_ok

        # Period sanity: start <= end lexicographically and counts correctness
        if schema_ok:
            start = period["start"]
            end = period["end"]
            days_val = float(period["days"])
            snaps_val = float(counts["snapshots"])
            order_ok = start <= end
            counts_ok = True
            # Compare with expected where available
            exp_days = expected.get("period_days")
            exp_snap_count = expected.get("snap_count")
            if isinstance(exp_days, int):
                counts_ok = counts_ok and approx_equal(days_val, float(exp_days))
            if isinstance(exp_snap_count, int):
                counts_ok = counts_ok and approx_equal(snaps_val, float(exp_snap_count))
            # If expected start/end exist, also compare
            exp_start = expected.get("period_start")
            exp_end = expected.get("period_end")
            if isinstance(exp_start, str):
                order_ok = order_ok and (start == exp_start)
            if isinstance(exp_end, str):
                order_ok = order_ok and (end == exp_end)
            checks["summary_period_values_valid"] = bool(order_ok and counts_ok)

        # Numeric correctness vs expected (with tolerance)
        if schema_ok:
            # bm25
            b_hit = bm25.get("hit_rate", {})
            b_avg = bm25.get("avg_score", {})
            eh = expected.get("bm25_hit_rate", {})
            ea = expected.get("bm25_avg_score", {})
            hit_ok = True
            avg_ok = True
            if all(v is not None for v in (eh.get("min"), eh.get("max"), eh.get("avg"))):
                hit_ok = (
                    approx_equal(b_hit["min"], eh["min"]) and
                    approx_equal(b_hit["max"], eh["max"]) and
                    approx_equal(b_hit["avg"], eh["avg"])
                )
            if all(v is not None for v in (ea.get("min"), ea.get("max"), ea.get("avg"))):
                avg_ok = (
                    approx_equal(b_avg["min"], ea["min"]) and
                    approx_equal(b_avg["max"], ea["max"]) and
                    approx_equal(b_avg["avg"], ea["avg"])
                )
            checks["summary_bm25_values_correct"] = bool(hit_ok and avg_ok)

            # index
            i_fc = index.get("file_count", {})
            i_cc = index.get("chunk_count", {})
            e_fc = expected.get("index_file_count", {})
            e_cc = expected.get("index_chunk_count", {})
            fc_ok = True
            cc_ok = True
            if all(v is not None for v in (e_fc.get("min"), e_fc.get("max"), e_fc.get("last"))):
                fc_ok = (
                    approx_equal(i_fc["min"], e_fc["min"]) and
                    approx_equal(i_fc["max"], e_fc["max"]) and
                    approx_equal(i_fc["last"], e_fc["last"])
                )
            if all(v is not None for v in (e_cc.get("min"), e_cc.get("max"), e_cc.get("last"))):
                cc_ok = (
                    approx_equal(i_cc["min"], e_cc["min"]) and
                    approx_equal(i_cc["max"], e_cc["max"]) and
                    approx_equal(i_cc["last"], e_cc["last"])
                )
            checks["summary_index_values_correct"] = bool(fc_ok and cc_ok)

            # gateway
            g_qe = gateway.get("qmd_errors", {})
            g_ss = gateway.get("session_saves", {})
            g_qa = gateway.get("qmd_armed", {})
            eg = expected.get("gateway", {})
            gw_ok = True
            conds = []
            if "qmd_errors_total" in eg and "qmd_errors_max_daily" in eg:
                conds.append(approx_equal(g_qe["total"], eg["qmd_errors_total"]))
                conds.append(approx_equal(g_qe["max_daily"], eg["qmd_errors_max_daily"]))
            if "session_saves_total" in eg:
                conds.append(approx_equal(g_ss["total"], eg["session_saves_total"]))
            if "qmd_armed_total" in eg:
                conds.append(approx_equal(g_qa["total"], eg["qmd_armed_total"]))
            if conds:
                gw_ok = all(conds)
            checks["summary_gateway_values_correct"] = gw_ok

    # 2) trend.md
    trend_path = os.path.join(telemetry_dir, "trend.md")
    if os.path.isfile(trend_path):
        checks["has_trend_file"] = True
        try:
            with open(trend_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f.readlines()]
            non_empty = [ln for ln in lines if ln.strip()]
            if non_empty:
                header = non_empty[0].lower()
                tokens = ["date", "files", "chunks", "hit%", "avgscore", "armed", "errors"]
                checks["trend_header_ok"] = all(tok in header for tok in tokens)
            checks["trend_min_rows"] = len(non_empty) >= 4  # header + >=3 rows
        except Exception:
            pass

    # 3) anomalies.json
    anomalies_path = os.path.join(telemetry_dir, "anomalies.json")
    anomalies = read_json(anomalies_path) if os.path.isfile(anomalies_path) else None
    if anomalies is not None:
        checks["has_anomalies_file"] = True
        schema_ok = False
        if isinstance(anomalies, list):
            schema_ok = True
            for item in anomalies:
                if not isinstance(item, dict):
                    schema_ok = False
                    break
                d = item.get("date")
                m = item.get("metric")
                v = item.get("value")
                t = item.get("threshold")
                direction = item.get("direction")
                if not (isinstance(d, str) and isinstance(m, str) and num(v) and num(t) and direction in ("above", "below")):
                    schema_ok = False
                    break
        checks["anomalies_schema_valid"] = schema_ok

    # 4) recommendations.txt
    rec_path = os.path.join(telemetry_dir, "recommendations.txt")
    if os.path.isfile(rec_path):
        checks["has_recommendations_file"] = True
        try:
            with open(rec_path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f.readlines()]
            non_empty = [ln for ln in lines if ln]
            checks["recommendations_min_lines"] = len(non_empty) >= 3
            joined = "\n".join(non_empty).lower()
            checks["recommendations_contains_keywords"] = any(k in joined for k in ["bm25", "index", "gateway"])
        except Exception:
            pass

    # Compute reward as fraction of passed checks; ensure 0 if no outputs present
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if telemetry dir missing or empty of required artifacts, force reward 0.0
    required_any = any([
        checks["has_summary_file"],
        checks["has_trend_file"],
        checks["has_anomalies_file"],
        checks["has_recommendations_file"],
    ])
    if not required_any:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()