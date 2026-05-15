import csv
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_iso8601_utc(ts: str) -> bool:
    if not isinstance(ts, str) or not ts.strip():
        return False
    s = ts.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
    except Exception:
        return False
    if dt.tzinfo is None:
        return False
    try:
        offset = dt.utcoffset()
    except Exception:
        return False
    return offset == timedelta(0)


def _parse_processes_csv(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows: List[Dict[str, Any]] = []
            for row in reader:
                rows.append(row)
        return rows, header
    except Exception:
        return None, None


def _convert_process_rows(raw_rows: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    for r in raw_rows:
        try:
            rank = int(str(r.get("rank", "")).strip())
            pid = int(str(r.get("pid", "")).strip())
            name = str(r.get("name", "")).strip()
            cpu = float(str(r.get("cpu_percent", "")).strip())
            mem = float(str(r.get("memory_mb", "")).strip())
            rows.append(
                {
                    "rank": rank,
                    "pid": pid,
                    "name": name,
                    "cpu_percent": cpu,
                    "memory_mb": mem,
                }
            )
        except Exception:
            return None
    return rows


def _is_sorted_and_ranked(rows: List[Dict[str, Any]]) -> bool:
    n = len(rows)
    for i, r in enumerate(rows):
        if r["rank"] != i + 1:
            return False
        cpu = r["cpu_percent"]
        mem = r["memory_mb"]
        if not (0.0 <= cpu <= 100.0):
            return False
        if mem < 0:
            return False
        if not isinstance(r["name"], str) or r["name"] == "":
            return False
    eps = 1e-6
    for i in range(1, n):
        prev = rows[i - 1]
        cur = rows[i]
        if prev["cpu_percent"] + eps < cur["cpu_percent"]:
            return False
        if abs(prev["cpu_percent"] - cur["cpu_percent"]) <= eps:
            if prev["memory_mb"] + eps < cur["memory_mb"]:
                return False
    return True


def _parse_verification_note(text: str) -> Tuple[Optional[float], Optional[int], bool]:
    seconds_val: Optional[float] = None
    mentions_seconds_word = False
    sec_pattern = re.compile(r"(\d+(?:\.\d+)?)\s*(seconds|second|secs|sec|s)\b", re.IGNORECASE)
    matches = list(sec_pattern.finditer(text))
    if matches:
        mentions_seconds_word = True
        try:
            seconds_val = max(float(m.group(1)) for m in matches)
        except Exception:
            seconds_val = None
    else:
        if re.search(r"at\s+least\s+1\s+second", text, re.IGNORECASE):
            mentions_seconds_word = True
            seconds_val = 1.0

    proc_count: Optional[int] = None
    m1 = re.search(r"\b(\d+)\s+process(?:es)?\b", text, re.IGNORECASE)
    if m1:
        try:
            proc_count = int(m1.group(1))
        except Exception:
            proc_count = None
    else:
        m2 = re.search(r"\b(\d+)\b.*\bprocess", text, re.IGNORECASE | re.DOTALL)
        if m2:
            try:
                proc_count = int(m2.group(1))
            except Exception:
                proc_count = None

    return seconds_val, proc_count, mentions_seconds_word


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _percent_value_in_text(text: str, value: float) -> bool:
    pattern = re.compile(r"(\d+(?:\.\d+)?)\s*(%|percent)\b", re.IGNORECASE)
    for m in pattern.finditer(text):
        try:
            num = float(m.group(1))
        except Exception:
            continue
        if abs(num - value) <= 0.5:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    output_dir = workspace / "output"
    input_dir = workspace / "input"

    scores: Dict[str, float] = {
        "processes_csv_valid": 0.0,
        "processes_sorted_and_ranked": 0.0,
        "processes_row_limit_respected": 0.0,
        "verification_note_consistent_with_csv": 0.0,
        "verification_sampling_duration_valid": 0.0,
        "system_snapshot_valid": 0.0,
        "methods_placeholders_replaced": 0.0,
        "methods_references_snapshot_values": 0.0,
        "lab_message_length_requirement": 0.0,
        "lab_message_mentions_top_process_and_cpu": 0.0,
        "lab_message_memory_free_note_correct": 0.0,
        "crossfile_top_process_consistency": 0.0,
    }

    rules = _load_json(input_dir / "process_filter_rules.json")
    max_rows: Optional[int] = None
    if isinstance(rules, dict) and isinstance(rules.get("max_rows"), int):
        max_rows = rules["max_rows"]

    proc_csv_path = output_dir / "processes_ranked.csv"
    raw_rows, header = _parse_processes_csv(proc_csv_path)
    proc_rows: Optional[List[Dict[str, Any]]] = None
    if raw_rows is not None and header is not None:
        expected_header = ["rank", "pid", "name", "cpu_percent", "memory_mb"]
        if header == expected_header:
            proc_rows = _convert_process_rows(raw_rows)
            if proc_rows is not None:
                basic_ok = True
                for r in proc_rows:
                    if not isinstance(r["pid"], int):
                        basic_ok = False
                        break
                    if not isinstance(r["name"], str) or r["name"] == "":
                        basic_ok = False
                        break
                    try:
                        float(r["cpu_percent"])
                        float(r["memory_mb"])
                    except Exception:
                        basic_ok = False
                        break
                if basic_ok:
                    scores["processes_csv_valid"] = 1.0

    if proc_rows is not None:
        if _is_sorted_and_ranked(proc_rows):
            scores["processes_sorted_and_ranked"] = 1.0
        if max_rows is not None:
            if len(proc_rows) <= max_rows:
                scores["processes_row_limit_respected"] = 1.0

    verification_path = output_dir / "verification.txt"
    ver_text = _read_text(verification_path)
    if ver_text is not None and proc_rows is not None:
        seconds_val, proc_count, mentions_seconds_word = _parse_verification_note(ver_text)
        if isinstance(proc_count, int) and proc_count == len(proc_rows):
            scores["verification_note_consistent_with_csv"] = 1.0
        if seconds_val is not None and seconds_val >= 1.0 and mentions_seconds_word:
            scores["verification_sampling_duration_valid"] = 1.0

    snapshot_path = output_dir / "system_snapshot.json"
    snapshot = _load_json(snapshot_path)
    if isinstance(snapshot, dict):
        required_keys = ["OS", "OS_RELEASE", "CPU_LOGICAL", "MEM_TOTAL_MB", "MEM_FREE_MB", "DISK_FREE_MB", "UPTIME_SECONDS", "TIMESTAMP"]
        has_all_keys = all(k in snapshot for k in required_keys)
        types_ok = True
        if has_all_keys:
            if not isinstance(snapshot["OS"], str) or not snapshot["OS"].strip():
                types_ok = False
            if not isinstance(snapshot["OS_RELEASE"], str) or not snapshot["OS_RELEASE"].strip():
                types_ok = False
            if not isinstance(snapshot["CPU_LOGICAL"], int) or snapshot["CPU_LOGICAL"] < 1:
                types_ok = False
            for key in ["MEM_TOTAL_MB", "MEM_FREE_MB", "DISK_FREE_MB"]:
                if not isinstance(snapshot[key], int) or snapshot[key] < 0:
                    types_ok = False
            if not isinstance(snapshot["UPTIME_SECONDS"], (int, float)) or snapshot["UPTIME_SECONDS"] < 0:
                types_ok = False
            if not isinstance(snapshot["TIMESTAMP"], str) or not _parse_iso8601_utc(snapshot["TIMESTAMP"]):
                types_ok = False
            if types_ok:
                scores["system_snapshot_valid"] = 1.0

    methods_out_path = output_dir / "methods_environment_section.md"
    methods_text = _read_text(methods_out_path)
    methods_template = _read_text(input_dir / "methods_template.md")
    if methods_text is not None:
        if "{{" not in methods_text and "}}" not in methods_text:
            scores["methods_placeholders_replaced"] = 1.0
        if isinstance(snapshot, dict):
            values_ok = True
            str_vals = []
            str_vals.append(str(snapshot.get("OS", "")))
            str_vals.append(str(snapshot.get("OS_RELEASE", "")))
            str_vals.append(str(snapshot.get("CPU_LOGICAL", "")))
            str_vals.append(str(snapshot.get("MEM_TOTAL_MB", "")))
            str_vals.append(str(snapshot.get("MEM_FREE_MB", "")))
            str_vals.append(str(snapshot.get("DISK_FREE_MB", "")))
            for sv in str_vals:
                if not sv or sv not in methods_text:
                    values_ok = False
                    break
            guidance_phrases_ok = True
            if methods_template:
                if "Replace the placeholders below and improve the readability." in methods_text:
                    guidance_phrases_ok = False
                if "The wording here is a bit clunky and might be too casual" in methods_text:
                    guidance_phrases_ok = False
            if values_ok and guidance_phrases_ok:
                scores["methods_references_snapshot_values"] = 1.0

    lab_msg_path = output_dir / "lab_message_polished.txt"
    lab_msg = _read_text(lab_msg_path)
    if lab_msg is not None:
        wc = _word_count(lab_msg)
        if 80 <= wc <= 120:
            scores["lab_message_length_requirement"] = 1.0
        if isinstance(snapshot, dict) and isinstance(snapshot.get("MEM_TOTAL_MB"), int) and isinstance(snapshot.get("MEM_FREE_MB"), int):
            total = snapshot["MEM_TOTAL_MB"]
            free = snapshot["MEM_FREE_MB"]
            ratio_ok = False
            if total > 0:
                ratio = free / total
                msg_lower = lab_msg.lower()
                mentions_25 = "25%" in msg_lower
                if ratio > 0.25:
                    ratio_ok = mentions_25 and ("above 25%" in msg_lower or "over 25%" in msg_lower)
                elif ratio < 0.25:
                    ratio_ok = mentions_25 and ("below 25%" in msg_lower or "under 25%" in msg_lower)
                else:
                    ratio_ok = mentions_25 and (("above 25%" in msg_lower or "over 25%" in msg_lower or "below 25%" in msg_lower or "under 25%" in msg_lower))
            if ratio_ok:
                scores["lab_message_memory_free_note_correct"] = 1.0

        if proc_rows is not None and len(proc_rows) > 0:
            top = proc_rows[0]
            name_included = top["name"].lower() in lab_msg.lower()
            cpu_included = _percent_value_in_text(lab_msg, float(top["cpu_percent"]))
            if name_included and cpu_included:
                scores["lab_message_mentions_top_process_and_cpu"] = 1.0
                scores["crossfile_top_process_consistency"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()