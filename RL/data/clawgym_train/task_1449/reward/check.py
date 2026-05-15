import json
import sys
import csv
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime


def _read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _load_json(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
            return rows, header, None
    except Exception as e:
        return None, None, str(e)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)


def _almost_equal(a: float, b: float, tol: float = 1e-3) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _parse_iso(ts: str) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    try:
        # Accept 'Z' suffix as UTC.
        if ts.endswith("Z"):
            datetime.fromisoformat(ts[:-1] + "+00:00")
        else:
            datetime.fromisoformat(ts)
        return True
    except Exception:
        return False


def _exact_keys(d: Dict[str, Any], expected_keys: List[str]) -> bool:
    return set(d.keys()) == set(expected_keys)


def _generate_number_strings(value: float, max_decimals: int = 3, include_percent: bool = False) -> List[str]:
    strs = set()
    try:
        v = float(value)
    except Exception:
        return []
    # Generate fixed-point representations from 0 to max_decimals
    for d in range(max_decimals + 1):
        s = f"{v:.{d}f}"
        # Normalize representations like '12.0' -> '12.0' and '12'
        strs.add(s)
        # Also add integer form if it rounds to an integer
        if d > 0:
            try:
                if abs(v - round(v)) <= 10 ** (-d):
                    strs.add(str(int(round(v))))
            except Exception:
                pass
    # Also add raw str(v) to capture default Python formatting
    strs.add(str(v))
    # Deduplicate and sort by length descending to match longer forms first
    bases = sorted(strs, key=lambda x: (-len(x), x))
    results = list(bases)
    if include_percent:
        for b in bases:
            results.append(b + "%")
    return results


def _find_section(text: str, title: str = "System Health Snapshot") -> Optional[str]:
    if text is None:
        return None
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if title.lower() in line.strip().lower():
            start_idx = i
            break
    if start_idx is None:
        return None
    # The section goes until the next markdown heading starting with '#', excluding the starting line
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("#"):
            end_idx = j
            break
    section = "\n".join(lines[start_idx:end_idx]).strip()
    return section if section else None


def _string_contains_any(text: str, candidates: List[str]) -> bool:
    text_lower = text.lower()
    for c in candidates:
        if c and c.lower() in text_lower:
            return True
    return False


def _number_present_in_text(text: str, value: float, allow_percent: bool = False) -> bool:
    if text is None:
        return False
    candidates = _generate_number_strings(value, max_decimals=3, include_percent=allow_percent)
    return _string_contains_any(text, candidates)


def _find_near(text: str, anchor: str, needles: List[str], radius: int = 120) -> bool:
    """Find an occurrence of anchor in text that has all needles within radius characters of the anchor location."""
    if text is None or not anchor:
        return False
    idx = 0
    found_any = False
    text_lower = text
    anchor_lower = anchor
    while True:
        pos = text_lower.find(anchor_lower, idx)
        if pos == -1:
            break
        found_any = True
        start = max(0, pos - radius)
        end = min(len(text_lower), pos + len(anchor_lower) + radius)
        window = text_lower[start:end]
        ok = True
        for n in needles:
            if not n:
                ok = False
                break
            if n.lower() not in window.lower():
                ok = False
                break
        if ok:
            return True
        idx = pos + 1
    # If anchor never appears, False; else still False if no window matched
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "json_schema_and_types": 0.0,
        "json_aggregates_correct": 0.0,
        "csv_structure_and_order_valid": 0.0,
        "csv_matches_json": 0.0,
        "markdown_updated_and_copied": 0.0,
        "markdown_summary_matches_outputs": 0.0,
    }

    # Paths
    json_path = workspace / "output" / "system_snapshot.json"
    csv_path = workspace / "output" / "process_stats.csv"
    md_path = workspace / "docs" / "writing_session_notes.md"
    md_copy_path = workspace / "output" / "writing_session_notes_with_snapshot.md"

    # Load files
    js, js_err = _load_json(json_path) if json_path.exists() else (None, "missing")
    csv_rows, csv_header, csv_err = _load_csv(csv_path) if csv_path.exists() else (None, None, "missing")
    md_text, md_err = _read_text(md_path) if md_path.exists() else (None, "missing")
    md_copy_text, md_copy_err = _read_text(md_copy_path) if md_copy_path.exists() else (None, "missing")

    # Check JSON schema and types
    json_ok = False
    processes_list: List[Dict[str, Any]] = []
    aggregates_obj: Dict[str, Any] = {}
    if js is not None and isinstance(js, dict):
        try:
            expected_top_keys = [
                "timestamp_iso",
                "os",
                "hostname",
                "user",
                "cpu",
                "memory",
                "disk",
                "battery",
                "processes",
                "aggregates",
            ]
            if not _exact_keys(js, expected_top_keys):
                raise ValueError("Top-level keys mismatch")

            # timestamp
            ts = js.get("timestamp_iso")
            if not isinstance(ts, str) or not _parse_iso(ts):
                raise ValueError("Invalid timestamp_iso")

            # os
            os_obj = js.get("os")
            if not isinstance(os_obj, dict) or not _exact_keys(os_obj, ["name", "version"]):
                raise ValueError("Invalid os object")
            if not isinstance(os_obj["name"], str) or not isinstance(os_obj["version"], str):
                raise ValueError("Invalid os fields")

            # hostname, user
            if not isinstance(js.get("hostname"), str):
                raise ValueError("Invalid hostname")
            if not isinstance(js.get("user"), str):
                raise ValueError("Invalid user")

            # cpu
            cpu_obj = js.get("cpu")
            if not isinstance(cpu_obj, dict) or not _exact_keys(cpu_obj, ["cores_physical", "cores_logical", "overall_percent"]):
                raise ValueError("Invalid cpu object")
            if not _is_int(cpu_obj["cores_physical"]) or cpu_obj["cores_physical"] <= 0:
                raise ValueError("Invalid cores_physical")
            if not _is_int(cpu_obj["cores_logical"]) or cpu_obj["cores_logical"] <= 0:
                raise ValueError("Invalid cores_logical")
            if not _is_number(cpu_obj["overall_percent"]) or not (0.0 <= float(cpu_obj["overall_percent"]) <= 100.0):
                raise ValueError("Invalid overall_percent")

            # memory
            mem_obj = js.get("memory")
            if not isinstance(mem_obj, dict) or not _exact_keys(mem_obj, ["total_mb", "available_mb"]):
                raise ValueError("Invalid memory object")
            if not _is_number(mem_obj["total_mb"]) or float(mem_obj["total_mb"]) <= 0:
                raise ValueError("Invalid total_mb")
            if not _is_number(mem_obj["available_mb"]) or float(mem_obj["available_mb"]) < 0:
                raise ValueError("Invalid available_mb")
            if float(mem_obj["available_mb"]) > float(mem_obj["total_mb"]):
                raise ValueError("available_mb greater than total_mb")

            # disk
            disk_obj = js.get("disk")
            if not isinstance(disk_obj, dict) or not _exact_keys(disk_obj, ["total_gb", "free_gb"]):
                raise ValueError("Invalid disk object")
            if not _is_number(disk_obj["total_gb"]) or float(disk_obj["total_gb"]) <= 0:
                raise ValueError("Invalid total_gb")
            if not _is_number(disk_obj["free_gb"]) or float(disk_obj["free_gb"]) < 0:
                raise ValueError("Invalid free_gb")
            if float(disk_obj["free_gb"]) > float(disk_obj["total_gb"]):
                raise ValueError("free_gb greater than total_gb")

            # battery
            batt_obj = js.get("battery")
            if not isinstance(batt_obj, dict) or not _exact_keys(batt_obj, ["percent", "plugged"]):
                raise ValueError("Invalid battery object")
            percent_ok = batt_obj["percent"] is None or _is_number(batt_obj["percent"])
            plugged_ok = batt_obj["plugged"] is None or isinstance(batt_obj["plugged"], bool)
            if not percent_ok or not plugged_ok:
                raise ValueError("Invalid battery fields")

            # processes
            proc_obj = js.get("processes")
            if not isinstance(proc_obj, dict) or not _exact_keys(proc_obj, ["top_n", "list"]):
                raise ValueError("Invalid processes object")
            if not _is_int(proc_obj["top_n"]) or proc_obj["top_n"] != 8:
                raise ValueError("Invalid processes.top_n")
            if not isinstance(proc_obj["list"], list) or len(proc_obj["list"]) != 8:
                raise ValueError("Invalid processes.list length")
            seen_pids = set()
            for item in proc_obj["list"]:
                if not isinstance(item, dict) or not _exact_keys(item, ["pid", "name", "cpu_percent", "mem_mb"]):
                    raise ValueError("Invalid process item structure")
                if not _is_int(item["pid"]):
                    raise ValueError("Invalid pid")
                if item["pid"] in seen_pids:
                    raise ValueError("Duplicate pid")
                seen_pids.add(item["pid"])
                if not isinstance(item["name"], str):
                    raise ValueError("Invalid name")
                if not _is_number(item["cpu_percent"]):
                    raise ValueError("Invalid cpu_percent")
                if not _is_number(item["mem_mb"]):
                    raise ValueError("Invalid mem_mb")
            processes_list = proc_obj["list"]

            # aggregates
            agg_obj = js.get("aggregates")
            if not isinstance(agg_obj, dict) or not _exact_keys(
                agg_obj, ["top_cpu_sum_percent", "top_cpu_avg_percent", "top_mem_sum_mb", "top_mem_avg_mb"]
            ):
                raise ValueError("Invalid aggregates object")
            for k in ["top_cpu_sum_percent", "top_cpu_avg_percent", "top_mem_sum_mb", "top_mem_avg_mb"]:
                if not _is_number(agg_obj[k]):
                    raise ValueError(f"Invalid aggregate {k}")
            aggregates_obj = agg_obj

            json_ok = True
        except Exception:
            json_ok = False

    if json_ok:
        scores["json_schema_and_types"] = 1.0

    # Aggregates correctness
    if json_ok:
        try:
            cpu_sum = sum(float(p["cpu_percent"]) for p in processes_list)
            mem_sum = sum(float(p["mem_mb"]) for p in processes_list)
            n = len(processes_list)
            cpu_avg = cpu_sum / n if n else 0.0
            mem_avg = mem_sum / n if n else 0.0
            ok = True
            ok &= _almost_equal(cpu_sum, aggregates_obj.get("top_cpu_sum_percent", None))
            ok &= _almost_equal(cpu_avg, aggregates_obj.get("top_cpu_avg_percent", None))
            ok &= _almost_equal(mem_sum, aggregates_obj.get("top_mem_sum_mb", None))
            ok &= _almost_equal(mem_avg, aggregates_obj.get("top_mem_avg_mb", None))
            if ok:
                scores["json_aggregates_correct"] = 1.0
        except Exception:
            pass

    # CSV structure and order
    csv_ok = False
    typed_csv_rows: List[Dict[str, Any]] = []
    if csv_rows is not None and isinstance(csv_rows, list) and csv_header is not None:
        try:
            expected_header = ["pid", "name", "cpu_percent", "mem_mb", "rank_by_cpu"]
            if csv_header != expected_header:
                raise ValueError("Header mismatch")
            if len(csv_rows) != 8:
                raise ValueError("Expected 8 rows")
            prev_cpu = float("inf")
            for idx, r in enumerate(csv_rows):
                pid = int(r["pid"])
                name = r["name"]
                cpu = float(r["cpu_percent"])
                mem = float(r["mem_mb"])
                rank = int(r["rank_by_cpu"])
                if rank != idx + 1:
                    raise ValueError("Rank mismatch or out of order")
                if cpu > prev_cpu + 1e-9:  # should be non-increasing
                    raise ValueError("Rows not sorted by cpu desc")
                prev_cpu = cpu
                typed_csv_rows.append({"pid": pid, "name": name, "cpu_percent": cpu, "mem_mb": mem, "rank_by_cpu": rank})
            csv_ok = True
        except Exception:
            csv_ok = False

    if csv_ok:
        scores["csv_structure_and_order_valid"] = 1.0

    # CSV matches JSON processes
    if csv_ok and json_ok:
        try:
            json_map = {int(p["pid"]): p for p in processes_list}
            csv_map = {int(r["pid"]): r for r in typed_csv_rows}
            if set(json_map.keys()) != set(csv_map.keys()):
                raise ValueError("PID sets differ")
            ok = True
            for pid, jp in json_map.items():
                rp = csv_map.get(pid)
                if rp is None:
                    ok = False
                    break
                if rp["name"] != jp["name"]:
                    ok = False
                    break
                if not _almost_equal(float(rp["cpu_percent"]), float(jp["cpu_percent"])):
                    ok = False
                    break
                if not _almost_equal(float(rp["mem_mb"]), float(jp["mem_mb"])):
                    ok = False
                    break
            if ok:
                scores["csv_matches_json"] = 1.0
        except Exception:
            pass

    # Markdown updated and copied
    md_ok = False
    section_text = None
    if md_text is not None:
        try:
            if "[[SYSTEM_HEALTH_SNAPSHOT]]" in md_text:
                md_ok = False
            else:
                section_text = _find_section(md_text, title="System Health Snapshot")
                if section_text is None:
                    md_ok = False
                else:
                    # Copy exists and identical to updated
                    if md_copy_text is None:
                        md_ok = False
                    else:
                        if md_copy_text == md_text:
                            md_ok = True
                        else:
                            md_ok = False
        except Exception:
            md_ok = False

    if md_ok:
        scores["markdown_updated_and_copied"] = 1.0

    # Markdown summary matches outputs
    md_values_ok = False
    if md_ok and json_ok and csv_ok and section_text:
        try:
            # Timestamp exact
            ts = js["timestamp_iso"]
            if ts not in section_text:
                raise ValueError("Timestamp not present")

            # OS name and version and hostname
            os_name = js["os"]["name"]
            os_ver = js["os"]["version"]
            hostname = js["hostname"]
            if os_name not in section_text or os_ver not in section_text or hostname not in section_text:
                raise ValueError("OS or hostname missing")

            # CPU cores and overall percent (allow % sign)
            cores_phys = js["cpu"]["cores_physical"]
            cores_log = js["cpu"]["cores_logical"]
            overall = float(js["cpu"]["overall_percent"])
            if not _number_present_in_text(section_text, float(cores_phys), allow_percent=False):
                raise ValueError("cores_physical missing")
            if not _number_present_in_text(section_text, float(cores_log), allow_percent=False):
                raise ValueError("cores_logical missing")
            if not _number_present_in_text(section_text, overall, allow_percent=True):
                raise ValueError("overall_percent missing")

            # Memory total and available MB
            mem_total = float(js["memory"]["total_mb"])
            mem_avail = float(js["memory"]["available_mb"])
            if not _number_present_in_text(section_text, mem_total, allow_percent=False):
                raise ValueError("memory total_mb missing")
            if not _number_present_in_text(section_text, mem_avail, allow_percent=False):
                raise ValueError("memory available_mb missing")

            # Disk total and free GB
            disk_total = float(js["disk"]["total_gb"])
            disk_free = float(js["disk"]["free_gb"])
            if not _number_present_in_text(section_text, disk_total, allow_percent=False):
                raise ValueError("disk total_gb missing")
            if not _number_present_in_text(section_text, disk_free, allow_percent=False):
                raise ValueError("disk free_gb missing")

            # Battery percent or N/A
            batt_percent = js["battery"]["percent"]
            if batt_percent is None:
                if "n/a" not in section_text.lower():
                    raise ValueError("Battery N/A missing")
            else:
                if not _number_present_in_text(section_text, float(batt_percent), allow_percent=True):
                    raise ValueError("Battery percent missing")

            # Top 3 processes by CPU: validate near mentions including name, pid, cpu_percent, mem_mb
            # Use CSV top 3 (already sorted by CPU)
            top3 = typed_csv_rows[:3]
            for proc in top3:
                name = proc["name"]
                pid_str = str(proc["pid"])
                # Prepare candidate strings for cpu and mem
                cpu_candidates = _generate_number_strings(float(proc["cpu_percent"]), max_decimals=3, include_percent=True)
                mem_candidates = _generate_number_strings(float(proc["mem_mb"]), max_decimals=3, include_percent=False)
                # Build a few "needles" that must be present in the window near the name
                # We'll require pid and at least one cpu and one mem candidate
                found = False
                # Try a few combinations
                for cpu_str in cpu_candidates[:6]:
                    for mem_str in mem_candidates[:6]:
                        if _find_near(section_text, name, [pid_str, cpu_str, mem_str], radius=160):
                            found = True
                            break
                    if found:
                        break
                if not found:
                    # As an alternative, try anchoring on pid
                    for cpu_str in cpu_candidates[:6]:
                        for mem_str in mem_candidates[:6]:
                            if _find_near(section_text, pid_str, [name, cpu_str, mem_str], radius=160):
                                found = True
                                break
                        if found:
                            break
                if not found:
                    raise ValueError(f"Top process entry for {name} ({pid_str}) not found with required details")

            # Aggregates numbers: sums and averages for cpu and mem
            agg = js["aggregates"]
            for key, allow_percent in [
                ("top_cpu_sum_percent", True),
                ("top_cpu_avg_percent", True),
                ("top_mem_sum_mb", False),
                ("top_mem_avg_mb", False),
            ]:
                if not _number_present_in_text(section_text, float(agg[key]), allow_percent=allow_percent):
                    raise ValueError(f"Aggregate {key} missing")

            md_values_ok = True
        except Exception:
            md_values_ok = False

    if md_values_ok:
        scores["markdown_summary_matches_outputs"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()