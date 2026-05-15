import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, List


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[dict]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_iso_dt(ts: str) -> Optional[datetime]:
    # Attempt common formats present in inputs
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts.strip(), fmt)
        except Exception:
            continue
    return None


def _compute_metrics_from_csv(path: Path) -> Optional[dict]:
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return None
    cpu_vals = []
    mem_vals = []
    disk_vals = []
    timestamps = []
    for r in rows:
        ts = r.get("timestamp")
        cpu = r.get("cpu_percent")
        mem = r.get("mem_used_mb")
        disk = r.get("disk_used_gb")
        if ts is None or cpu is None or mem is None or disk is None:
            return None
        try:
            cpu_f = float(cpu)
            mem_f = float(mem)
            disk_f = float(disk)
        except Exception:
            return None
        dt = _parse_iso_dt(ts)
        if dt is None:
            return None
        cpu_vals.append(cpu_f)
        mem_vals.append(mem_f)
        disk_vals.append(disk_f)
        timestamps.append(dt)
    if not cpu_vals:
        return None
    overall = {
        "overall_avg_cpu_percent": sum(cpu_vals) / len(cpu_vals),
        "max_cpu_percent": max(cpu_vals),
        "overall_avg_mem_used_mb": sum(mem_vals) / len(mem_vals),
        "max_mem_used_mb": max(mem_vals),
        "overall_avg_disk_used_gb": sum(disk_vals) / len(disk_vals),
        "max_disk_used_gb": max(disk_vals),
        "net_disk_growth_gb": disk_vals[-1] - disk_vals[0],
        "earliest_date": min(timestamps).date().isoformat(),
        "latest_date": max(timestamps).date().isoformat(),
    }
    # daily stats
    daily: Dict[str, Dict[str, float]] = {}
    counts: Dict[str, int] = {}
    for i, dt in enumerate(timestamps):
        d = dt.date().isoformat()
        daily.setdefault(d, {"cpu_sum": 0.0, "mem_sum": 0.0})
        counts.setdefault(d, 0)
        daily[d]["cpu_sum"] += cpu_vals[i]
        daily[d]["mem_sum"] += mem_vals[i]
        counts[d] += 1
    daily_avgs = {}
    for d, sums in daily.items():
        c = counts[d]
        if c == 0:
            return None
        daily_avgs[d] = {
            "avg_cpu_percent": sums["cpu_sum"] / c,
            "avg_mem_used_mb": sums["mem_sum"] / c,
        }
    overall["daily_avgs"] = daily_avgs
    return overall


def _parse_syslog_counts(path: Path) -> Optional[Tuple[Dict[str, int], Dict[str, Dict[str, int]]]]:
    txt = _safe_read_text(path)
    if txt is None:
        return None
    totals = {"INFO": 0, "WARNING": 0, "ERROR": 0}
    per_proc: Dict[str, Dict[str, int]] = {}
    # Regex: timestamp severity process[pid]:
    pattern = re.compile(r'^\S+\s+(INFO|WARNING|ERROR)\s+([A-Za-z0-9_.-]+)\[\d+\]:')
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if not m:
            # If any line cannot be parsed, consider failure
            return None
        sev = m.group(1)
        proc = m.group(2)
        if sev not in totals:
            return None
        totals[sev] += 1
        if proc not in per_proc:
            per_proc[proc] = {"INFO": 0, "WARNING": 0, "ERROR": 0}
        per_proc[proc][sev] += 1
    return totals, per_proc


def _find_number_near(text: str, keyword: str, expected_value: float, tol: float = 0.1, window: int = 80) -> bool:
    found = False
    for m in re.finditer(re.escape(keyword), text, flags=re.IGNORECASE):
        start = max(0, m.start() - window)
        end = min(len(text), m.end() + window)
        segment = text[start:end]
        for nm in re.finditer(r'[-+]?\d+(?:\.\d+)?', segment):
            try:
                val = float(nm.group(0))
            except Exception:
                continue
            if abs(val - expected_value) <= tol:
                return True
        found = True
    # If keyword not found at all, try the whole text as fallback (less strict)
    if not found:
        for nm in re.finditer(r'[-+]?\d+(?:\.\d+)?', text):
            try:
                val = float(nm.group(0))
            except Exception:
                continue
            if abs(val - expected_value) <= tol:
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_summary_structure": 0.0,
        "metrics_summary_values": 0.0,
        "daily_stats_structure": 0.0,
        "daily_stats_values": 0.0,
        "syslog_counts_structure": 0.0,
        "syslog_counts_values": 0.0,
        "top_error_processes_structure": 0.0,
        "top_error_processes_values_and_sort": 0.0,
        "top_error_processes_match_syslog_counts": 0.0,
        "health_report_markers_and_outside_preserved": 0.0,
        "health_report_dates_and_stats": 0.0,
        "health_report_severity_totals": 0.0,
        "health_report_top_error_processes_listed": 0.0,
        "health_report_links_to_outputs": 0.0,
    }

    # Load inputs
    metrics_csv = workspace / "input" / "system_metrics.csv"
    syslog_txt = workspace / "input" / "syslog.txt"
    draft_md = workspace / "input" / "notes" / "health_report_draft.md"

    metrics = None
    if metrics_csv.exists():
        metrics = _compute_metrics_from_csv(metrics_csv)
    syslog_counts = None
    if syslog_txt.exists():
        syslog_counts = _parse_syslog_counts(syslog_txt)

    # Expected results
    expected_metrics = metrics
    expected_totals = None
    expected_perproc = None
    if syslog_counts is not None:
        expected_totals, expected_perproc = syslog_counts
    expected_top_errors_sorted: List[Tuple[str, int]] = []
    if expected_perproc is not None:
        for proc, sev_counts in expected_perproc.items():
            err = sev_counts.get("ERROR", 0)
            if err > 0:
                expected_top_errors_sorted.append((proc, err))
        expected_top_errors_sorted.sort(key=lambda x: (-x[1], x[0]))

    # Check metrics_summary.csv
    out_metrics_summary = workspace / "output" / "metrics_summary.csv"
    rows = _safe_read_csv_dicts(out_metrics_summary)
    if rows is not None:
        # Structure: headers metric,value only
        headers_ok = False
        try:
            with out_metrics_summary.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header == ["metric", "value"]:
                    headers_ok = True
        except Exception:
            headers_ok = False
        if headers_ok:
            scores["metrics_summary_structure"] = 1.0
        required_keys = [
            "overall_avg_cpu_percent",
            "max_cpu_percent",
            "overall_avg_mem_used_mb",
            "max_mem_used_mb",
            "overall_avg_disk_used_gb",
            "max_disk_used_gb",
            "net_disk_growth_gb",
        ]
        if expected_metrics is not None and headers_ok:
            values_ok = True
            found_map = {r.get("metric"): r.get("value") for r in rows if "metric" in r and "value" in r}
            for k in required_keys:
                if k not in found_map:
                    values_ok = False
                    break
                v = found_map[k]
                vf = _parse_float(v)
                if vf is None:
                    values_ok = False
                    break
                exp = expected_metrics[k]
                if not _approx_equal(vf, float(exp), tol=1e-6):
                    values_ok = False
                    break
            if values_ok:
                scores["metrics_summary_values"] = 1.0

    # Check daily_stats.csv
    out_daily_stats = workspace / "output" / "daily_stats.csv"
    rows = _safe_read_csv_dicts(out_daily_stats)
    if rows is not None:
        # Check headers exactly
        headers_ok = False
        try:
            with out_daily_stats.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header == ["date", "avg_cpu_percent", "avg_mem_used_mb"]:
                    headers_ok = True
        except Exception:
            headers_ok = False
        if headers_ok:
            scores["daily_stats_structure"] = 1.0
        if expected_metrics is not None and headers_ok:
            expected_daily = expected_metrics.get("daily_avgs", {})
            # Build map from output
            out_map = {}
            valid_parse = True
            dates_set = set()
            for r in rows:
                d = r.get("date")
                ac = r.get("avg_cpu_percent")
                am = r.get("avg_mem_used_mb")
                if d is None or ac is None or am is None:
                    valid_parse = False
                    break
                try:
                    acf = float(ac)
                    amf = float(am)
                except Exception:
                    valid_parse = False
                    break
                out_map[d] = {"avg_cpu_percent": acf, "avg_mem_used_mb": amf}
                dates_set.add(d)
            if valid_parse and set(out_map.keys()) == set(expected_daily.keys()):
                all_ok = True
                for d, vals in expected_daily.items():
                    ov = out_map.get(d)
                    if ov is None:
                        all_ok = False
                        break
                    if not _approx_equal(ov["avg_cpu_percent"], vals["avg_cpu_percent"], tol=1e-6):
                        all_ok = False
                        break
                    if not _approx_equal(ov["avg_mem_used_mb"], vals["avg_mem_used_mb"], tol=1e-6):
                        all_ok = False
                        break
                if all_ok:
                    scores["daily_stats_values"] = 1.0

    # Check syslog_counts.json
    out_syslog_counts = workspace / "output" / "syslog_counts.json"
    data = _safe_load_json(out_syslog_counts)
    if data is not None and isinstance(data, dict):
        struct_ok = False
        if "totals" in data and "per_process" in data and isinstance(data["totals"], dict) and isinstance(data["per_process"], dict):
            # Check keys present with int values
            t = data["totals"]
            sev_keys = ["INFO", "WARNING", "ERROR"]
            if all(k in t and isinstance(t[k], int) for k in sev_keys):
                # per_process types
                per_ok = True
                for proc, counts in data["per_process"].items():
                    if not isinstance(counts, dict):
                        per_ok = False
                        break
                    if not all(k in counts and isinstance(counts[k], int) for k in sev_keys):
                        per_ok = False
                        break
                if per_ok:
                    struct_ok = True
        if struct_ok:
            scores["syslog_counts_structure"] = 1.0
        if expected_totals is not None and expected_perproc is not None and struct_ok:
            values_ok = True
            # Compare totals
            for k in ["INFO", "WARNING", "ERROR"]:
                if data["totals"].get(k) != expected_totals.get(k):
                    values_ok = False
                    break
            # Compare per_process for processes present in input
            if values_ok:
                for proc, exp_counts in expected_perproc.items():
                    got = data["per_process"].get(proc)
                    if got is None:
                        values_ok = False
                        break
                    for k in ["INFO", "WARNING", "ERROR"]:
                        if got.get(k) != exp_counts.get(k):
                            values_ok = False
                            break
                    if not values_ok:
                        break
            if values_ok:
                scores["syslog_counts_values"] = 1.0

    # Check top_error_processes.csv
    out_top_errors = workspace / "output" / "top_error_processes.csv"
    rows = _safe_read_csv_dicts(out_top_errors)
    if rows is not None:
        headers_ok = False
        try:
            with out_top_errors.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header == ["process", "error_count"]:
                    headers_ok = True
        except Exception:
            headers_ok = False
        if headers_ok:
            scores["top_error_processes_structure"] = 1.0
        if headers_ok:
            parsed_rows: List[Tuple[str, int]] = []
            parse_ok = True
            for r in rows:
                proc = r.get("process")
                ec = r.get("error_count")
                if proc is None or ec is None:
                    parse_ok = False
                    break
                try:
                    ec_i = int(ec)
                except Exception:
                    parse_ok = False
                    break
                parsed_rows.append((proc, ec_i))
            if parse_ok and expected_top_errors_sorted:
                # Values and sorting check
                if parsed_rows == expected_top_errors_sorted:
                    scores["top_error_processes_values_and_sort"] = 1.0
                # Cross-file consistency with syslog_counts.json if available
                syslog_json = _safe_load_json(out_syslog_counts)
                consistent = False
                if syslog_json and isinstance(syslog_json, dict) and "per_process" in syslog_json:
                    consistent = True
                    per = syslog_json["per_process"]
                    # ensure each parsed row matches json ERROR count
                    for proc, ec in parsed_rows:
                        j = per.get(proc)
                        if not isinstance(j, dict) or not isinstance(j.get("ERROR"), int) or j.get("ERROR") != ec:
                            consistent = False
                            break
                    # ensure all processes with ERROR>0 in json appear in top file
                    if consistent:
                        json_err_procs = sorted([(p, v.get("ERROR", 0)) for p, v in per.items() if isinstance(v, dict) and v.get("ERROR", 0) > 0],
                                                key=lambda x: (-x[1], x[0]))
                        if json_err_procs != parsed_rows:
                            consistent = False
                if consistent:
                    scores["top_error_processes_match_syslog_counts"] = 1.0

    # Health report: output/PC_health_report.md
    out_report = workspace / "output" / "PC_health_report.md"
    out_text = _safe_read_text(out_report)
    draft_text = _safe_read_text(draft_md) if draft_md.exists() else None
    if out_text is not None and draft_text is not None:
        start_marker = "<!-- SYSTEM_SUMMARY_START -->"
        end_marker = "<!-- SYSTEM_SUMMARY_END -->"
        if start_marker in draft_text and end_marker in draft_text and start_marker in out_text and end_marker in out_text:
            # Extract segments
            draft_before = draft_text.split(start_marker)[0]
            draft_after = draft_text.split(end_marker)[-1]
            out_before = out_text.split(start_marker)[0]
            out_after = out_text.split(end_marker)[-1]
            before_ok = (draft_before == out_before)
            after_ok = (draft_after == out_after)
            # Extract between
            draft_between = draft_text.split(start_marker)[1].split(end_marker)[0]
            out_between = out_text.split(start_marker)[1].split(end_marker)[0]
            replaced = (out_between.strip() != draft_between.strip()) and ("[Placeholder]" not in out_between)
            if before_ok and after_ok and replaced:
                scores["health_report_markers_and_outside_preserved"] = 1.0

            # Prepare expected references
            earliest = expected_metrics["earliest_date"] if expected_metrics else None
            latest = expected_metrics["latest_date"] if expected_metrics else None
            avg_cpu = expected_metrics["overall_avg_cpu_percent"] if expected_metrics else None
            peak_mem = expected_metrics["max_mem_used_mb"] if expected_metrics else None
            net_disk_growth = expected_metrics["net_disk_growth_gb"] if expected_metrics else None
            # dates and stats
            dates_ok = False
            stats_ok = False
            if earliest and latest:
                # Require both ISO date strings to appear
                if (earliest in out_between) and (latest in out_between):
                    # Also check presence of CPU average near "CPU" and peak mem near "mem" and disk growth near "disk"
                    cpu_ok = False
                    mem_ok = False
                    disk_ok = False
                    if avg_cpu is not None:
                        cpu_ok = _find_number_near(out_between, "cpu", float(avg_cpu), tol=0.1, window=100)
                    if peak_mem is not None:
                        mem_ok = _find_number_near(out_between, "mem", float(peak_mem), tol=0.1, window=120) or _find_number_near(out_between, "memory", float(peak_mem), tol=0.1, window=120)
                    if net_disk_growth is not None:
                        disk_ok = _find_number_near(out_between, "disk", float(net_disk_growth), tol=0.05, window=120)
                    stats_ok = cpu_ok and mem_ok and disk_ok
                    dates_ok = True
            if dates_ok and stats_ok:
                scores["health_report_dates_and_stats"] = 1.0

            # severity totals in summary
            sev_ok = False
            if expected_totals is not None:
                info_ok = _find_number_near(out_between, "INFO", float(expected_totals["INFO"]), tol=0.0, window=50)
                warn_ok = _find_number_near(out_between, "WARNING", float(expected_totals["WARNING"]), tol=0.0, window=50)
                err_ok = _find_number_near(out_between, "ERROR", float(expected_totals["ERROR"]), tol=0.0, window=50)
                sev_ok = info_ok and warn_ok and err_ok
            if sev_ok:
                scores["health_report_severity_totals"] = 1.0

            # top error processes listed in summary
            top_ok = False
            if expected_top_errors_sorted:
                # Require each process and its error count appear near each other
                all_present = True
                for proc, cnt in expected_top_errors_sorted:
                    # look for process name
                    found_pair = False
                    for m in re.finditer(re.escape(proc), out_between, flags=re.IGNORECASE):
                        start = max(0, m.start() - 30)
                        end = min(len(out_between), m.end() + 30)
                        seg = out_between[start:end]
                        # search for exact count
                        if re.search(r'\b{}\b'.format(re.escape(str(cnt))), seg):
                            found_pair = True
                            break
                    if not found_pair:
                        all_present = False
                        break
                if all_present:
                    top_ok = True
            if top_ok:
                scores["health_report_top_error_processes_listed"] = 1.0

            # links to outputs
            links_ok = all(
                s in out_between
                for s in [
                    "output/metrics_summary.csv",
                    "output/daily_stats.csv",
                    "output/syslog_counts.json",
                    "output/top_error_processes.csv",
                ]
            )
            if links_ok:
                scores["health_report_links_to_outputs"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()