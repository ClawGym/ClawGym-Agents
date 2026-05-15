import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text_lines(path: Path) -> Optional[List[str]]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not text:
            return None
        reader = csv.reader(text)
        rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None


def _to_gb(size_str: str) -> Optional[float]:
    # Converts human-readable sizes like "120G" to GB float
    try:
        s = size_str.strip()
        if not s:
            return None
        # Extract number and unit
        match = re.match(r"^\s*([\d\.]+)\s*([KMGTP]?)(i?B)?\s*$", s, re.IGNORECASE)
        if match:
            num = float(match.group(1))
            unit = match.group(2).upper()
            # Convert to GB
            if unit == "T":
                return num * 1024.0
            if unit == "G" or unit == "":
                return num
            if unit == "M":
                return num / 1024.0
            if unit == "K":
                return num / (1024.0 * 1024.0)
            if unit == "P":
                return num * 1024.0 * 1024.0
            return num
        # If pure number
        return float(s)
    except Exception:
        return None


def _parse_df_output(path: Path) -> Optional[Dict[str, float]]:
    lines = _read_text_lines(path)
    if lines is None:
        return None
    for line in lines:
        if not line.strip():
            continue
        if line.strip().startswith("Filesystem"):
            continue
        parts = line.split()
        # Expect: Filesystem Size Used Avail Use% Mounted_on
        if len(parts) < 6:
            continue
        mount = parts[-1]
        if mount == "/":
            size = _to_gb(parts[1])
            used = _to_gb(parts[2])
            use_pct_str = parts[4].strip()
            if use_pct_str.endswith("%"):
                use_pct_str = use_pct_str[:-1]
            try:
                used_pct = float(use_pct_str)
            except Exception:
                return None
            if size is None or used is None:
                return None
            return {"total_gb": float(size), "used_gb": float(used), "used_pct": float(used_pct)}
    return None


def _parse_free_output(path: Path) -> Optional[Dict[str, float]]:
    lines = _read_text_lines(path)
    if lines is None:
        return None
    for line in lines:
        if line.strip().startswith("Mem:"):
            parts = line.split()
            # parts: ["Mem:", total, used, free, shared, buff/cache, available]
            if len(parts) < 3:
                return None
            try:
                total = float(parts[1])
                used = float(parts[2])
            except Exception:
                return None
            used_pct = round((used / total) * 100.0, 1) if total > 0 else 0.0
            return {"total_mb": total, "used_mb": used, "used_pct": used_pct}
    return None


def _parse_ps_output(path: Path) -> Optional[Dict[str, object]]:
    lines = _read_text_lines(path)
    if lines is None or not lines:
        return None
    header_line = None
    for i, line in enumerate(lines):
        if line.strip().startswith("USER"):
            header_line = line
            start_idx = i + 1
            break
    if header_line is None:
        return None
    header_tokens = header_line.split()
    if "USER" not in header_tokens or "PID" not in header_tokens or "%MEM" not in header_tokens or "COMMAND" not in header_tokens:
        return None
    idx_user = header_tokens.index("USER")
    idx_pid = header_tokens.index("PID")
    idx_mem = header_tokens.index("%MEM")
    idx_cmd = header_tokens.index("COMMAND")
    top = None  # tuple (mem_pct, user, pid, command)
    for line in lines[start_idx:]:
        if not line.strip():
            continue
        tokens = line.split()
        if len(tokens) <= idx_cmd:
            continue
        try:
            user = tokens[idx_user]
            pid = int(tokens[idx_pid])
            mem_pct = float(tokens[idx_mem])
            command = " ".join(tokens[idx_cmd:])
        except Exception:
            continue
        if (top is None) or (mem_pct > top[0]):
            top = (mem_pct, user, pid, command)
    if top is None:
        return None
    return {"user": top[1], "pid": top[2], "mem_pct": top[0], "command": top[3]}


def _list_log_files(logs_dir: Path) -> List[Path]:
    if not logs_dir.exists() or not logs_dir.is_dir():
        return []
    return sorted([p for p in logs_dir.iterdir() if p.is_file() and p.name.endswith(".log")])


def _count_logs_and_errors(log_files: List[Path]) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int]]:
    per_file_counts: Dict[str, Dict[str, int]] = {}
    error_messages: Dict[str, int] = {}
    for lf in log_files:
        lines = _read_text_lines(lf) or []
        fcounts = {"ERROR": 0, "WARN": 0}
        for line in lines:
            if "ERROR" in line:
                fcounts["ERROR"] += 1
                # Extract message after literal "ERROR:"
                idx = line.find("ERROR:")
                if idx != -1:
                    msg = line[idx + len("ERROR:"):].strip()
                    if msg:
                        error_messages[msg] = error_messages.get(msg, 0) + 1
            if "WARN" in line:
                fcounts["WARN"] += 1
        # Only include levels that appear (count > 0)
        per_file_counts[lf.name] = {k: v for k, v in fcounts.items() if v > 0}
    return per_file_counts, error_messages


def _parse_du_tours(path: Path) -> Optional[List[Tuple[str, float]]]:
    lines = _read_text_lines(path)
    if lines is None:
        return None
    result: List[Tuple[str, float]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\s*([\d\.]+)\s+(.+)$", line)
        if not m:
            return None
        try:
            size_mb = float(m.group(1))
            subdir = m.group(2).strip()
            result.append((subdir, size_mb))
        except Exception:
            return None
    if not result:
        return None
    return result


def _approx_equal(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(float(a) - float(b)) <= tol


def _approx_equal_1dp(a: float, b: float) -> bool:
    # tighter tolerance for values rounded to 1 decimal place
    return abs(float(a) - float(b)) <= 0.1


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "health_summary_disk": 0.0,
        "health_summary_memory": 0.0,
        "health_summary_top_process": 0.0,
        "health_summary_log_totals": 0.0,
        "tours_storage_csv": 0.0,
        "log_summary_csv": 0.0,
        "top_errors_csv": 0.0,
        "health_report_opener": 0.0,
        "health_report_disk_summary": 0.0,
        "health_report_memory_summary": 0.0,
        "health_report_top_process": 0.0,
        "health_report_log_totals": 0.0,
        "health_report_top_three_errors": 0.0,
        "health_report_references": 0.0,
    }

    # Input paths
    df_path = workspace / "input" / "snapshots" / "df_output.txt"
    free_path = workspace / "input" / "snapshots" / "free_output.txt"
    ps_path = workspace / "input" / "snapshots" / "ps_output.txt"
    du_tours_path = workspace / "input" / "snapshots" / "du_tours_mb.txt"
    logs_dir = workspace / "input" / "logs"

    # Output paths
    health_summary_path = workspace / "output" / "health_summary.json"
    tours_storage_path = workspace / "output" / "tours_storage.csv"
    log_summary_path = workspace / "output" / "log_summary.csv"
    top_errors_path = workspace / "output" / "top_errors.csv"
    health_report_path = workspace / "output" / "health_report.md"

    # Compute expected values
    expected_disk = _parse_df_output(df_path)
    expected_mem = _parse_free_output(free_path)
    expected_top_proc = _parse_ps_output(ps_path)

    log_files = _list_log_files(logs_dir)
    per_file_counts, error_messages = _count_logs_and_errors(log_files)

    expected_errors_total = None
    expected_warnings_total = None
    if log_files:
        expected_errors_total = sum(per_file_counts.get(p.name, {}).get("ERROR", 0) for p in log_files)
        expected_warnings_total = sum(per_file_counts.get(p.name, {}).get("WARN", 0) for p in log_files)

    # 1) health_summary.json checks
    hs = _load_json(health_summary_path)
    if hs and isinstance(hs, dict):
        # Disk
        if expected_disk is not None and isinstance(hs.get("disk"), dict):
            disk = hs.get("disk")
            try:
                tg = float(disk.get("total_gb"))
                ug = float(disk.get("used_gb"))
                up = float(disk.get("used_pct"))
                if _approx_equal(tg, expected_disk["total_gb"]) and _approx_equal(ug, expected_disk["used_gb"]) and _approx_equal(up, expected_disk["used_pct"]):
                    scores["health_summary_disk"] = 1.0
            except Exception:
                pass
        # Memory
        if expected_mem is not None and isinstance(hs.get("memory"), dict):
            mem = hs.get("memory")
            try:
                tm = float(mem.get("total_mb"))
                um = float(mem.get("used_mb"))
                upct = float(mem.get("used_pct"))
                if _approx_equal(tm, expected_mem["total_mb"]) and _approx_equal(um, expected_mem["used_mb"]) and _approx_equal_1dp(upct, expected_mem["used_pct"]):
                    scores["health_summary_memory"] = 1.0
            except Exception:
                pass
        # Top memory process
        if expected_top_proc is not None and isinstance(hs.get("top_memory_process"), dict):
            tp = hs.get("top_memory_process")
            try:
                user_ok = str(tp.get("user")) == expected_top_proc["user"]
                pid_ok = int(tp.get("pid")) == int(expected_top_proc["pid"])
                mem_ok = _approx_equal(float(tp.get("mem_pct")), float(expected_top_proc["mem_pct"]))
                cmd_ok = str(tp.get("command")) == expected_top_proc["command"]
                if user_ok and pid_ok and mem_ok and cmd_ok:
                    scores["health_summary_top_process"] = 1.0
            except Exception:
                pass
        # Logs totals
        if expected_errors_total is not None and expected_warnings_total is not None and isinstance(hs.get("logs"), dict):
            lg = hs.get("logs")
            try:
                eok = int(lg.get("errors_total")) == int(expected_errors_total)
                wok = int(lg.get("warnings_total")) == int(expected_warnings_total)
                if eok and wok:
                    scores["health_summary_log_totals"] = 1.0
            except Exception:
                pass

    # 2) tours_storage.csv checks
    expected_tours = _parse_du_tours(du_tours_path)
    if expected_tours is not None:
        # Build expected map: subdir -> (size_mb, percent_rounded_1dp)
        total_mb = sum(v for _, v in expected_tours)
        expected_rows = []
        for subdir, size in expected_tours:
            pct = round((size / total_mb) * 100.0, 1) if total_mb > 0 else 0.0
            expected_rows.append((subdir, size, pct))
        loaded = _load_csv_rows(tours_storage_path)
        if loaded:
            header, data = loaded
            if header == ["subdir", "size_mb", "percent_of_total"]:
                # Parse rows
                got_rows = []
                ok_parse = True
                for row in data:
                    if len(row) != 3:
                        ok_parse = False
                        break
                    subdir = row[0]
                    try:
                        size_mb = float(row[1])
                        pct = float(row[2])
                    except Exception:
                        ok_parse = False
                        break
                    got_rows.append((subdir, size_mb, pct))
                if ok_parse:
                    # Compare ignoring order; require all expected and no extras
                    def match_row(g, exp):
                        return (g[0] == exp[0]) and _approx_equal(g[1], exp[1]) and _approx_equal_1dp(g[2], exp[2])
                    unmatched_expected = expected_rows.copy()
                    matched = []
                    for g in got_rows:
                        found = None
                        for e in unmatched_expected:
                            if match_row(g, e):
                                found = e
                                break
                        if found:
                            matched.append(g)
                            unmatched_expected.remove(found)
                        else:
                            # extra or mismatched row
                            unmatched_expected = None
                            break
                    if unmatched_expected == [] and len(matched) == len(expected_rows):
                        scores["tours_storage_csv"] = 1.0

    # 3) log_summary.csv checks
    if log_files:
        # Build expected rows sorted by file asc, level asc ("ERROR" then "WARN")
        expected_log_rows = []
        for f in sorted([p.name for p in log_files]):
            counts = per_file_counts.get(f, {})
            for level in ["ERROR", "WARN"]:
                if counts.get(level, 0) > 0:
                    expected_log_rows.append([f, level, str(counts[level])])
        loaded = _load_csv_rows(log_summary_path)
        if loaded:
            header, data = loaded
            if header == ["file", "level", "count"]:
                # Verify sorting: by file asc, then level asc
                sorted_data = sorted(data, key=lambda r: (r[0], r[1]))
                if data == sorted_data:
                    # Compare equality with expected
                    # Also ensure counts are exact integers
                    try:
                        ok_int = all(row[2].strip().isdigit() for row in data)
                    except Exception:
                        ok_int = False
                    if ok_int and data == expected_log_rows:
                        scores["log_summary_csv"] = 1.0

    # 4) top_errors.csv checks
    if log_files:
        # Aggregate and sort: count desc, message asc
        items = list(error_messages.items())
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        expected_top_errors = [[msg, str(cnt)] for msg, cnt in items]
        loaded = _load_csv_rows(top_errors_path)
        if loaded:
            header, data = loaded
            if header == ["message", "count"]:
                # Validate counts as integers and exact order/content
                try:
                    counts_ok = all(row[1].strip().isdigit() for row in data)
                except Exception:
                    counts_ok = False
                if counts_ok and data == expected_top_errors:
                    scores["top_errors_csv"] = 1.0

    # 5) health_report.md checks
    # Build expected facts for matching
    expected_top3_msgs = []
    if log_files:
        items = list(error_messages.items())
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        expected_top3_msgs = items[:3]

    report_lines = _read_text_lines(health_report_path)
    if report_lines is not None:
        text = "\n".join(report_lines)
        # opener: first line contains "Keelung" (case-insensitive)
        if report_lines:
            first_line = report_lines[0].strip()
            if first_line and re.search(r"keelung", first_line, re.IGNORECASE):
                scores["health_report_opener"] = 1.0
        # disk summary: line containing "Disk" and expected numbers
        if expected_disk is not None:
            numbers_ok = False
            for line in report_lines:
                if re.search(r"disk", line, re.IGNORECASE):
                    if all(str(int(expected_disk[k] if k != "used_pct" else int(expected_disk[k]))) in line for k in ["total_gb", "used_gb", "used_pct"]):
                        numbers_ok = True
                        break
                    # fallback for float formatting: check as plain numbers
                    if (str(int(expected_disk["total_gb"])) in line and
                        str(int(expected_disk["used_gb"])) in line and
                        re.search(rf"\b{int(expected_disk['used_pct'])}\b", line)):
                        numbers_ok = True
                        break
            if numbers_ok:
                scores["health_report_disk_summary"] = 1.0
        # memory summary: line containing "Memory" and expected numbers including 1dp percent
        if expected_mem is not None:
            mem_ok = False
            upct_str = f"{expected_mem['used_pct']:.1f}"
            for line in report_lines:
                if re.search(r"memory", line, re.IGNORECASE):
                    if (str(int(expected_mem["total_mb"])) in line and
                        str(int(expected_mem["used_mb"])) in line and
                        upct_str in line):
                        mem_ok = True
                        break
            if mem_ok:
                scores["health_report_memory_summary"] = 1.0
        # top process presence: ensure user, pid, mem_pct, and command all present in file
        if expected_top_proc is not None:
            try:
                if (re.search(rf"\b{re.escape(str(expected_top_proc['user']))}\b", text) and
                    re.search(rf"\b{int(expected_top_proc['pid'])}\b", text) and
                    re.search(rf"\b{float(expected_top_proc['mem_pct']):.1f}\b", text) and
                    expected_top_proc["command"] in text):
                    scores["health_report_top_process"] = 1.0
            except Exception:
                pass
        # totals of ERROR and WARN
        if expected_errors_total is not None and expected_warnings_total is not None:
            err_ok = any(("ERROR" in line and re.search(rf"\b{expected_errors_total}\b", line)) for line in report_lines)
            warn_ok = any(("WARN" in line and re.search(rf"\b{expected_warnings_total}\b", line)) for line in report_lines)
            if err_ok and warn_ok:
                scores["health_report_log_totals"] = 1.0
        # top three error messages with their counts in order
        if expected_top3_msgs:
            # Find lines that contain these messages and verify order and that count appears in the same line
            order_indices = []
            success = True
            for msg, cnt in expected_top3_msgs:
                found_idx = -1
                for idx, line in enumerate(report_lines):
                    if msg in line and re.search(rf"\b{cnt}\b", line):
                        found_idx = idx
                        break
                if found_idx == -1:
                    success = False
                    break
                order_indices.append(found_idx)
            if success and order_indices == sorted(order_indices):
                scores["health_report_top_three_errors"] = 1.0
        # references to CSV files
        refs_ok = ("output/tours_storage.csv" in text) and ("output/log_summary.csv" in text)
        if refs_ok:
            scores["health_report_references"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()