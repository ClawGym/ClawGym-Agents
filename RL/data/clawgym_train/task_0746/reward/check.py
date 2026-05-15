import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _approx_equal(a: Any, b: Any, tol: float) -> bool:
    fa = _safe_float(a)
    fb = _safe_float(b)
    if fa is None or fb is None:
        return False
    return abs(fa - fb) <= tol


def _get_marked_sections(text: str, start_marker: str, end_marker: str) -> Optional[Tuple[str, str, str]]:
    si = text.find(start_marker)
    ei = text.find(end_marker)
    if si == -1 or ei == -1 or ei < si:
        return None
    before = text[: si + len(start_marker)]
    middle = text[si + len(start_marker) : ei]
    after = text[ei:]
    return before, middle, after


def _extract_percent_numbers(line: str) -> List[float]:
    nums: List[float] = []
    for m in re.finditer(r'(-?\d+(?:\.\d+)?)\s*%+', line):
        try:
            nums.append(float(m.group(1)))
        except Exception:
            pass
    # Also allow bare numbers in context of percent lines
    if not nums:
        for m in re.finditer(r'(-?\d+(?:\.\d+)?)', line):
            try:
                nums.append(float(m.group(1)))
            except Exception:
                pass
    return nums


def _extract_numbers_with_unit(line: str, unit: str) -> List[float]:
    nums: List[float] = []
    pattern = r'(-?\d+(?:\.\d+)?)\s*' + re.escape(unit)
    for m in re.finditer(pattern, line, flags=re.IGNORECASE):
        try:
            nums.append(float(m.group(1)))
        except Exception:
            pass
    return nums


def _lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip() != ""]


def _compute_expected(workspace: Path) -> Dict[str, Any]:
    expected: Dict[str, Any] = {
        "disk": None,
        "photos": None,
        "performance": None,
        "cross_checks": None,
        "alerts": [],
        "alerts_by_type": {},
        "log_window": None,
    }
    disk_rows = _read_csv_dicts(workspace / "input/system/disk_report.csv")
    cpu_rows = _read_csv_dicts(workspace / "input/system/cpu_mem_log.csv")
    pic_rows = _read_csv_dicts(workspace / "input/system/pictures_inventory.csv")

    # Disk
    if disk_rows is not None:
        disk_list = []
        valid = True
        for r in disk_rows:
            mount = r.get("mount")
            size_gb = _safe_float(r.get("size_gb"))
            used_gb = _safe_float(r.get("used_gb"))
            avail_gb = _safe_float(r.get("available_gb"))
            if mount is None or size_gb is None or used_gb is None or avail_gb is None or size_gb == 0:
                valid = False
                break
            used_pct = used_gb / size_gb * 100.0
            disk_list.append({
                "mount": mount,
                "size_gb": size_gb,
                "used_gb": used_gb,
                "avail_gb": avail_gb,
                "used_pct": used_pct,
            })
        if valid:
            expected["disk"] = disk_list

    # Photos
    if pic_rows is not None:
        total_files = len(pic_rows)
        total_mb = 0.0
        largest_mb = 0.0
        folder_map: Dict[str, Dict[str, Any]] = {}
        valid = True
        for r in pic_rows:
            size_mb = _safe_float(r.get("size_mb"))
            folder = r.get("folder")
            if size_mb is None or folder is None:
                valid = False
                break
            total_mb += size_mb
            largest_mb = max(largest_mb, size_mb)
            if folder not in folder_map:
                folder_map[folder] = {"file_count": 0, "total_mb": 0.0}
            folder_map[folder]["file_count"] += 1
            folder_map[folder]["total_mb"] += size_mb
        if valid:
            avg_mb = (total_mb / total_files) if total_files > 0 else 0.0
            total_gb = total_mb / 1024.0
            by_folder = []
            for folder, info in folder_map.items():
                by_folder.append({
                    "folder": folder,
                    "file_count": info["file_count"],
                    "total_size_gb": info["total_mb"] / 1024.0,
                })
            expected["photos"] = {
                "total_files": total_files,
                "total_size_gb": total_gb,
                "avg_file_size_mb": avg_mb,
                "largest_file_mb": largest_mb,
                "by_folder": by_folder,
            }

    # Performance and log window
    if cpu_rows is not None:
        cpu_vals: List[float] = []
        mem_vals: List[float] = []
        timestamps: List[str] = []
        valid = True
        for r in cpu_rows:
            cpu = _safe_float(r.get("cpu_percent"))
            mem = _safe_float(r.get("mem_used_mb"))
            ts = r.get("timestamp")
            if cpu is None or mem is None or ts is None:
                valid = False
                break
            cpu_vals.append(cpu)
            mem_vals.append(mem)
            timestamps.append(ts)
        if valid:
            cpu_avg = (sum(cpu_vals) / len(cpu_vals)) if cpu_vals else 0.0
            cpu_max = max(cpu_vals) if cpu_vals else 0.0
            mem_avg = (sum(mem_vals) / len(mem_vals)) if mem_vals else 0.0
            mem_max = max(mem_vals) if mem_vals else 0.0
            expected["performance"] = {
                "cpu_avg_pct": cpu_avg,
                "cpu_max_pct": cpu_max,
                "mem_avg_mb": mem_avg,
                "mem_max_mb": mem_max,
            }
            if timestamps:
                expected["log_window"] = (min(timestamps), max(timestamps))

    # Cross checks
    if expected["photos"] is not None and expected["disk"] is not None:
        pics_total_gb = expected["photos"]["total_size_gb"]
        pics_used = None
        for d in expected["disk"]:
            if d["mount"] == "Pictures":
                pics_used = d["used_gb"]
                break
        if pics_used is not None:
            discrepancy = abs(pics_total_gb - pics_used)
            expected["cross_checks"] = {
                "pictures_inventory_total_gb": pics_total_gb,
                "disk_report_pictures_used_gb": pics_used,
                "discrepancy_gb": discrepancy,
            }

    # Alerts expected based on thresholds
    alerts: List[Dict[str, Any]] = []
    alerts_by_type: Dict[str, List[Dict[str, Any]]] = {}

    # Disk usage
    if expected["disk"] is not None:
        for d in expected["disk"]:
            if d["used_pct"] >= 85.0:
                item = {"type": "disk_usage", "mount": d["mount"], "value": d["used_pct"], "threshold": 85.0}
                alerts.append(item)
                alerts_by_type.setdefault("disk_usage", []).append(item)

    # Pictures discrepancy
    if expected["cross_checks"] is not None:
        disc = expected["cross_checks"]["discrepancy_gb"]
        if disc > 0.20:
            item = {"type": "pictures_discrepancy", "value": disc, "threshold": 0.20}
            alerts.append(item)
            alerts_by_type.setdefault("pictures_discrepancy", []).append(item)

    # CPU average
    if expected["performance"] is not None:
        if expected["performance"]["cpu_avg_pct"] >= 75.0:
            item = {"type": "cpu_average", "value": expected["performance"]["cpu_avg_pct"], "threshold": 75.0}
            alerts.append(item)
            alerts_by_type.setdefault("cpu_average", []).append(item)
        # Memory peak
        if expected["performance"]["mem_max_mb"] >= 8000.0:
            item = {"type": "memory_peak", "value": expected["performance"]["mem_max_mb"], "threshold": 8000.0}
            alerts.append(item)
            alerts_by_type.setdefault("memory_peak", []).append(item)

    expected["alerts"] = alerts
    expected["alerts_by_type"] = alerts_by_type

    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "system_summary_json_present_and_well_formed": 0.0,
        "disk_section_matches_inputs": 0.0,
        "photos_section_matches_inputs": 0.0,
        "performance_section_matches_inputs": 0.0,
        "cross_checks_section_correct": 0.0,
        "alerts_json_matches_rules": 0.0,
        "alerts_csv_header_and_rows_correct": 0.0,
        "alerts_json_csv_consistent": 0.0,
        "notes_file_written": 0.0,
        "notes_preserved_outside_markers": 0.0,
        "notes_log_window_line_correct": 0.0,
        "notes_includes_disk_usage_by_mount": 0.0,
        "notes_includes_photo_totals_and_by_folder": 0.0,
        "notes_includes_performance_stats": 0.0,
        "notes_includes_alerts_line_when_needed": 0.0,
    }

    expected = _compute_expected(workspace)

    # Check system_summary.json
    sys_json_path = workspace / "output/system_summary.json"
    sys_json = _load_json(sys_json_path)
    if isinstance(sys_json, dict):
        # structure presence
        required_top = ["disk", "photos", "performance", "cross_checks", "alerts"]
        if all(k in sys_json for k in required_top):
            scores["system_summary_json_present_and_well_formed"] = 1.0

        # disk section verify per mount
        if expected["disk"] is not None and isinstance(sys_json.get("disk"), list):
            exp_map = {d["mount"]: d for d in expected["disk"]}
            checks = 0
            ok = 0
            for mount, exp in exp_map.items():
                # find item
                item = None
                for d in sys_json["disk"]:
                    if isinstance(d, dict) and d.get("mount") == mount:
                        item = d
                        break
                checks += 1
                if item is None:
                    continue
                size_ok = _approx_equal(item.get("size_gb"), exp["size_gb"], 0.01)
                used_ok = _approx_equal(item.get("used_gb"), exp["used_gb"], 0.01)
                avail_ok = _approx_equal(item.get("avail_gb"), exp["avail_gb"], 0.01)
                usedpct_ok = _approx_equal(item.get("used_pct"), exp["used_pct"], 0.05)
                if size_ok and used_ok and avail_ok and usedpct_ok:
                    ok += 1
            if checks > 0:
                scores["disk_section_matches_inputs"] = ok / checks

        # photos section
        if expected["photos"] is not None and isinstance(sys_json.get("photos"), dict):
            outp = sys_json["photos"]
            checks = 0
            ok = 0
            # total_files
            checks += 1
            if outp.get("total_files") == expected["photos"]["total_files"]:
                ok += 1
            # total_size_gb
            checks += 1
            if _approx_equal(outp.get("total_size_gb"), expected["photos"]["total_size_gb"], 0.02):
                ok += 1
            # avg_file_size_mb
            checks += 1
            if _approx_equal(outp.get("avg_file_size_mb"), expected["photos"]["avg_file_size_mb"], 0.1):
                ok += 1
            # largest_file_mb
            checks += 1
            if _approx_equal(outp.get("largest_file_mb"), expected["photos"]["largest_file_mb"], 0.01):
                ok += 1
            # by_folder
            checks += 1
            byf = outp.get("by_folder")
            if isinstance(byf, list):
                exp_by = {b["folder"]: b for b in expected["photos"]["by_folder"]}
                folder_ok = True
                for folder, expb in exp_by.items():
                    match = None
                    for item in byf:
                        if isinstance(item, dict) and item.get("folder") == folder:
                            match = item
                            break
                    if match is None:
                        folder_ok = False
                        break
                    if not (match.get("file_count") == expb["file_count"] and _approx_equal(match.get("total_size_gb"), expb["total_size_gb"], 0.02)):
                        folder_ok = False
                        break
                if folder_ok:
                    ok += 1
            if checks > 0:
                scores["photos_section_matches_inputs"] = ok / checks

        # performance section
        if expected["performance"] is not None and isinstance(sys_json.get("performance"), dict):
            outpf = sys_json["performance"]
            checks = 0
            ok = 0
            checks += 1
            if _approx_equal(outpf.get("cpu_avg_pct"), expected["performance"]["cpu_avg_pct"], 0.1):
                ok += 1
            checks += 1
            if _approx_equal(outpf.get("cpu_max_pct"), expected["performance"]["cpu_max_pct"], 0.01):
                ok += 1
            checks += 1
            if _approx_equal(outpf.get("mem_avg_mb"), expected["performance"]["mem_avg_mb"], 1.0):
                ok += 1
            checks += 1
            if _approx_equal(outpf.get("mem_max_mb"), expected["performance"]["mem_max_mb"], 0.01):
                ok += 1
            if checks > 0:
                scores["performance_section_matches_inputs"] = ok / checks

        # cross checks section
        if expected["cross_checks"] is not None and isinstance(sys_json.get("cross_checks"), dict):
            outcc = sys_json["cross_checks"]
            checks = 0
            ok = 0
            for key, tol in [
                ("pictures_inventory_total_gb", 0.02),
                ("disk_report_pictures_used_gb", 0.02),
                ("discrepancy_gb", 0.02),
            ]:
                checks += 1
                if _approx_equal(outcc.get(key), expected["cross_checks"][key], tol):
                    ok += 1
            if checks > 0:
                scores["cross_checks_section_correct"] = ok / checks

        # alerts in JSON
        exp_alerts = expected["alerts"]
        out_alerts = sys_json.get("alerts")
        if isinstance(out_alerts, list):
            # check length
            if len(out_alerts) == len(exp_alerts):
                # check types multiset
                out_types = [a.get("type") for a in out_alerts if isinstance(a, dict)]
                exp_types = [a.get("type") for a in exp_alerts]
                out_types_sorted = sorted([t for t in out_types if t is not None])
                exp_types_sorted = sorted([t for t in exp_types if t is not None])
                if out_types_sorted == exp_types_sorted:
                    scores["alerts_json_matches_rules"] = 1.0

    # alerts.csv
    alerts_csv_path = workspace / "output/alerts.csv"
    alerts_csv_ok = 0.0
    alerts_consistency_ok = 0.0
    if alerts_csv_path.exists():
        # Read raw header
        header = None
        try:
            with alerts_csv_path.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        header_ok = header == ["alert_type", "message", "value", "threshold"]
        rows = _read_csv_dicts(alerts_csv_path)
        if rows is not None and header_ok:
            exp = expected["alerts"]
            # Validate rows count and types
            types_out = [r.get("alert_type") for r in rows]
            types_exp = [a["type"] for a in exp]
            if len(types_out) == len(types_exp) and sorted(types_out) == sorted(types_exp):
                # Validate values and thresholds approximately plus minimal message content
                all_ok = True
                # Build index by type to compare multiples if any
                out_by_type: Dict[str, List[Dict[str, str]]] = {}
                for r in rows:
                    out_by_type.setdefault(r.get("alert_type"), []).append(r)
                exp_by_type: Dict[str, List[Dict[str, Any]]] = {}
                for a in exp:
                    exp_by_type.setdefault(a["type"], []).append(a)
                for t, exp_list in exp_by_type.items():
                    out_list = out_by_type.get(t, [])
                    if len(out_list) != len(exp_list):
                        all_ok = False
                        break
                    # Compare value/threshold presence
                    for i, e in enumerate(exp_list):
                        r = out_list[i]
                        val_ok = _approx_equal(r.get("value"), e["value"], 0.2 if t in ("disk_usage", "cpu_average") else 0.05)
                        thr_ok = _approx_equal(r.get("threshold"), e["threshold"], 0.001)
                        msg_ok = True
                        msg = (r.get("message") or "")
                        if t == "disk_usage":
                            # Must name mount
                            msg_ok = e.get("mount") in msg
                        elif t == "pictures_discrepancy":
                            msg_ok = ("picture" in msg.lower()) or ("photo" in msg.lower())
                        elif t == "cpu_average":
                            msg_ok = ("cpu" in msg.lower())
                        elif t == "memory_peak":
                            msg_ok = ("mem" in msg.lower())
                        if not (val_ok and thr_ok and msg_ok):
                            all_ok = False
                            break
                    if not all_ok:
                        break
                if all_ok:
                    alerts_csv_ok = 1.0

            # Consistency between JSON and CSV (types and count)
            sys_json = _load_json(workspace / "output/system_summary.json")
            if isinstance(sys_json, dict) and isinstance(sys_json.get("alerts"), list):
                out_types_json = sorted([a.get("type") for a in sys_json["alerts"] if isinstance(a, dict)])
                if sorted(types_out) == out_types_json:
                    alerts_consistency_ok = 1.0
    scores["alerts_csv_header_and_rows_correct"] = alerts_csv_ok
    scores["alerts_json_csv_consistent"] = alerts_consistency_ok

    # Notes checks
    input_notes_path = workspace / "input/Photo-Backup-Notes.md"
    output_notes_path = workspace / "output/Photo-Backup-Notes.md"
    in_notes = _read_text(input_notes_path)
    out_notes = _read_text(output_notes_path)
    if out_notes is not None:
        scores["notes_file_written"] = 1.0
    START = "<!-- HEALTH_SUMMARY_START -->"
    END = "<!-- HEALTH_SUMMARY_END -->"
    if in_notes is not None and out_notes is not None:
        in_parts = _get_marked_sections(in_notes, START, END)
        out_parts = _get_marked_sections(out_notes, START, END)
        if in_parts is not None and out_parts is not None:
            in_before, _, in_after = in_parts
            out_before, out_middle, out_after = out_parts
            # Preserve
            if in_before == out_before and in_after == out_after:
                scores["notes_preserved_outside_markers"] = 1.0

            # Log window line
            log_score = 0.0
            if expected["log_window"] is not None:
                earliest, latest = expected["log_window"]
                target = f"Log window: {earliest} to {latest}"
                if target in out_middle:
                    log_score = 1.0
            scores["notes_log_window_line_correct"] = log_score

            # Disk usage by mount lines
            disk_section_score = 0.0
            if expected["disk"] is not None:
                out_lines = _lines(out_middle)
                found = 0
                total = len(expected["disk"])
                for d in expected["disk"]:
                    mount = d["mount"]
                    used_pct = d["used_pct"]
                    matched = False
                    for ln in out_lines:
                        if mount == "/":
                            if ("/home" in ln) or ("Pictures" in ln):
                                continue
                            if "/" not in ln:
                                continue
                            nums = _extract_percent_numbers(ln)
                            if any(_approx_equal(n, used_pct, 0.3) for n in nums):
                                matched = True
                                break
                        else:
                            if mount in ln:
                                nums = _extract_percent_numbers(ln)
                                if any(_approx_equal(n, used_pct, 0.3) for n in nums):
                                    matched = True
                                    break
                    if matched:
                        found += 1
                if total > 0:
                    disk_section_score = found / total
            scores["notes_includes_disk_usage_by_mount"] = disk_section_score

            # Photo totals and by-folder
            photos_score = 0.0
            sub_checks = 0
            out_lines2 = _lines(out_middle)
            # total files
            sub_checks += 1
            file_ok = False
            if expected["photos"] is not None:
                tfiles = expected["photos"]["total_files"]
                for ln in out_lines2:
                    if re.search(r'\bfiles?\b', ln, flags=re.IGNORECASE):
                        for m in re.finditer(r'\b(\d+)\b', ln):
                            try:
                                if int(m.group(1)) == tfiles:
                                    file_ok = True
                                    break
                            except Exception:
                                pass
                    if file_ok:
                        break
            if file_ok:
                photos_score += 1.0
            # total size GB
            sub_checks += 1
            size_ok = False
            if expected["photos"] is not None:
                tgb = expected["photos"]["total_size_gb"]
                for ln in out_lines2:
                    gbs = _extract_numbers_with_unit(ln, "GB")
                    if any(_approx_equal(n, tgb, 0.05) for n in gbs):
                        size_ok = True
                        break
            if size_ok:
                photos_score += 1.0
            # avg file size MB
            sub_checks += 1
            avg_ok = False
            if expected["photos"] is not None:
                avg = expected["photos"]["avg_file_size_mb"]
                for ln in out_lines2:
                    if re.search(r'\b(avg|average|mean)\b', ln, flags=re.IGNORECASE):
                        mbs = _extract_numbers_with_unit(ln, "MB")
                        if any(_approx_equal(n, avg, 0.5) for n in mbs):
                            avg_ok = True
                            break
            if avg_ok:
                photos_score += 1.0
            # largest MB
            sub_checks += 1
            largest_ok = False
            if expected["photos"] is not None:
                largest = expected["photos"]["largest_file_mb"]
                for ln in out_lines2:
                    if re.search(r'\b(largest|max|peak)\b', ln, flags=re.IGNORECASE):
                        mbs = _extract_numbers_with_unit(ln, "MB")
                        if any(_approx_equal(n, largest, 0.5) for n in mbs):
                            largest_ok = True
                            break
            if largest_ok:
                photos_score += 1.0
            # by-folder line presence: all folder names must appear somewhere
            sub_checks += 1
            byfolder_ok = False
            if expected["photos"] is not None:
                folders = [b["folder"] for b in expected["photos"]["by_folder"]]
                if folders:
                    byfolder_ok = all(any(f in ln for ln in out_lines2) for f in folders)
            if byfolder_ok:
                photos_score += 1.0
            if sub_checks > 0:
                scores["notes_includes_photo_totals_and_by_folder"] = photos_score / sub_checks

            # Performance stats
            perf_score = 0.0
            perf_checks = 0
            if expected["performance"] is not None:
                # CPU avg and max on a cpu line
                perf_checks += 1
                cpu_avg_ok = False
                for ln in out_lines2:
                    if re.search(r'\bcpu\b', ln, flags=re.IGNORECASE):
                        nums = _extract_percent_numbers(ln)
                        if any(_approx_equal(n, expected["performance"]["cpu_avg_pct"], 0.5) for n in nums):
                            cpu_avg_ok = True
                            break
                if cpu_avg_ok:
                    perf_score += 1.0
                perf_checks += 1
                cpu_max_ok = False
                for ln in out_lines2:
                    if re.search(r'\bcpu\b', ln, flags=re.IGNORECASE):
                        nums = _extract_percent_numbers(ln)
                        if any(_approx_equal(n, expected["performance"]["cpu_max_pct"], 0.1) for n in nums):
                            cpu_max_ok = True
                            break
                if cpu_max_ok:
                    perf_score += 1.0
                # Memory avg and max on a memory line
                perf_checks += 1
                mem_avg_ok = False
                for ln in out_lines2:
                    if re.search(r'\bmem(ory)?\b', ln, flags=re.IGNORECASE):
                        mbs = _extract_numbers_with_unit(ln, "MB")
                        if any(_approx_equal(n, expected["performance"]["mem_avg_mb"], 5.0) for n in mbs):
                            mem_avg_ok = True
                            break
                if mem_avg_ok:
                    perf_score += 1.0
                perf_checks += 1
                mem_max_ok = False
                for ln in out_lines2:
                    if re.search(r'\bmem(ory)?\b', ln, flags=re.IGNORECASE):
                        mbs = _extract_numbers_with_unit(ln, "MB")
                        if any(_approx_equal(n, expected["performance"]["mem_max_mb"], 1.0) for n in mbs):
                            mem_max_ok = True
                            break
                if mem_max_ok:
                    perf_score += 1.0
            if perf_checks > 0:
                scores["notes_includes_performance_stats"] = perf_score / perf_checks

            # Alerts line when needed
            alerts_line_score = 0.0
            exp_alerts_count = len(expected["alerts"])
            if exp_alerts_count > 0:
                # find a line mentioning "alert" and the number and types
                types_needed = sorted([a["type"] for a in expected["alerts"]])
                found_line = False
                for ln in out_lines2:
                    if "alert" in ln.lower():
                        # number
                        numbers = [int(m.group(1)) for m in re.finditer(r'\b(\d+)\b', ln)]
                        has_num = any(n == exp_alerts_count for n in numbers)
                        has_types = all(t in ln for t in types_needed)
                        if has_num and has_types:
                            found_line = True
                            break
                if found_line:
                    alerts_line_score = 1.0
            else:
                # No alerts expected; not required to include an alerts line
                alerts_line_score = 1.0
            scores["notes_includes_alerts_line_when_needed"] = alerts_line_score

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()