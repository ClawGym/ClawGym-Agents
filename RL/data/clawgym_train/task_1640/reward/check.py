import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = list(reader)
            return (reader.fieldnames, rows)
    except Exception:
        return None


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _parse_systemctl_failed(path: Path) -> Optional[List[Dict[str, str]]]:
    """
    Parse logs/systemctl_failed.txt to identify failed services and descriptions.
    Returns list of dicts: {"service": unit, "description": description}
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    results: List[Dict[str, str]] = []
    for ln in lines:
        if "●" in ln and " failed " in f" {ln} ":
            parts = re.split(r"\s{2,}", ln.strip())
            if len(parts) >= 5:
                unit = parts[0].replace("●", "").strip()
                description = parts[-1].strip()
                results.append({"service": unit, "description": description})
    return results


def _extract_primary_errors(journal_path: Path, failed: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """
    From logs/journal_errors.txt extract primary error per failed service:
    - Prefer non-systemd daemon error lines related to the service (bluetoothd/dockerd/etc.)
    - Otherwise, fall back to the 'Failed to start ...' line matching the service description.
    Returns mapping service unit -> primary_error message (text after process colon).
    """
    text = _read_text(journal_path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    primary: Dict[str, str] = {}
    for item in failed:
        unit = item["service"]
        desc = item["description"]
        unit_l = unit.lower()
        desc_l = desc.lower()
        candidates = []
        for ln in lines:
            lnl = ln.lower()
            if "systemd[" in lnl:
                continue
            if "docker" in unit_l or "docker" in desc_l:
                if "dockerd" in lnl or "docker" in lnl:
                    candidates.append(ln)
            elif "bluetooth" in unit_l or "bluetooth" in desc_l:
                if "bluetoothd" in lnl or "bluetooth" in lnl:
                    candidates.append(ln)
            elif "network-manager" in unit_l or "network manager" in desc_l:
                # No daemon log expected; rely on fallback
                pass
        chosen_msg: Optional[str] = None
        if candidates:
            ln = candidates[0]
            if "]: " in ln:
                chosen_msg = ln.split("]: ", 1)[1].strip()
            else:
                parts = ln.split(": ", 1)
                chosen_msg = parts[1].strip() if len(parts) > 1 else ln.strip()
        if not chosen_msg:
            fallback_line = None
            pattern = f"Failed to start {desc}".lower()
            for ln in lines:
                if "systemd[" in ln and pattern in ln.lower():
                    fallback_line = ln
                    break
            if fallback_line:
                chosen_msg = fallback_line.split("]: ", 1)[1].strip() if "]: " in fallback_line else fallback_line.strip()
        if chosen_msg:
            primary[unit] = chosen_msg
    return primary


def _compute_power_summary(samples_path: Path) -> Optional[Dict[str, float]]:
    """
    Compute power summary metrics from logs/power_samples.csv.
    Returns dict with all required fields as computed from the CSV.
    """
    parsed = _parse_csv(samples_path)
    if parsed is None:
        return None
    headers, rows = parsed
    expected_headers = ["timestamp", "battery_pct", "power_w"]
    if headers != expected_headers:
        return None
    if not rows:
        return None
    timestamps: List[datetime] = []
    battery_pcts: List[float] = []
    power_ws: List[float] = []
    for row in rows:
        ts = _parse_iso(row.get("timestamp", ""))
        if ts is None:
            return None
        try:
            bp = float(row.get("battery_pct", ""))
            pw = float(row.get("power_w", ""))
        except Exception:
            return None
        timestamps.append(ts)
        battery_pcts.append(bp)
        power_ws.append(pw)
    start_ts = timestamps[0]
    end_ts = timestamps[-1]
    try:
        delta_seconds = (end_ts - start_ts).total_seconds()
        time_window_minutes = delta_seconds / 60.0
    except Exception:
        return None
    start_battery = battery_pcts[0]
    end_battery = battery_pcts[-1]
    net_drop_pct = start_battery - end_battery
    if time_window_minutes <= 0:
        return None
    avg_drain_per_hour = net_drop_pct / (time_window_minutes / 60.0)
    mean_power_w = sum(power_ws) / len(power_ws) if power_ws else 0.0
    min_power_w = min(power_ws) if power_ws else 0.0
    max_power_w = max(power_ws) if power_ws else 0.0
    try:
        est_hours_to_20 = (start_battery - 20.0) / avg_drain_per_hour if avg_drain_per_hour != 0 else float("inf")
    except Exception:
        return None
    return {
        "start_timestamp": rows[0]["timestamp"],
        "end_timestamp": rows[-1]["timestamp"],
        "time_window_minutes": time_window_minutes,
        "start_battery_pct": start_battery,
        "end_battery_pct": end_battery,
        "net_drop_pct": net_drop_pct,
        "avg_drain_pct_per_hour": avg_drain_per_hour,
        "mean_power_w": mean_power_w,
        "min_power_w": min_power_w,
        "max_power_w": max_power_w,
        "est_hours_to_20pct_from_start": est_hours_to_20,
    }


def _json_number_string(value) -> str:
    try:
        s = json.dumps(value, ensure_ascii=False)
        return s.strip()
    except Exception:
        return str(value)


def _find_section(lines: List[str], header_line: str) -> Tuple[int, int]:
    """
    Find a section in markdown lines given an exact header line.
    Returns (start_idx, end_idx_exclusive). If not found, returns (-1, -1).
    """
    start_idx = -1
    for i, ln in enumerate(lines):
        if ln.strip() == header_line:
            start_idx = i
            break
    if start_idx == -1:
        return (-1, -1)
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("## "):
            end_idx = j
            break
    return (start_idx, end_idx)


def _count_sentences(text: str) -> int:
    matches = re.findall(r"[\.!?](?:\s|$)", text)
    return len(matches)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "failed_services_csv_headers_correct": 0.0,
        "failed_services_csv_rows_match": 0.0,
        "power_summary_json_fields_and_types": 0.0,
        "power_summary_json_values_correct": 0.0,
        "power_summary_validation_consistency": 0.0,
        "readme_header_replaced_and_date": 0.0,
        "readme_contains_paragraph_1_to_3_sentences": 0.0,
        "readme_metrics_bullets_match_json": 0.0,
        "readme_failed_services_listed_with_quotes": 0.0,
        "readme_structure_preserved_titles": 0.0,
    }

    sys_failed_path = workspace / "logs" / "systemctl_failed.txt"
    journal_path = workspace / "logs" / "journal_errors.txt"
    power_samples_path = workspace / "logs" / "power_samples.csv"
    csv_out_path = workspace / "reports" / "failed_services.csv"
    json_out_path = workspace / "reports" / "power_summary.json"
    readme_path = workspace / "docs" / "README.md"

    expected_failed = _parse_systemctl_failed(sys_failed_path) or []
    expected_primary = _extract_primary_errors(journal_path, expected_failed) if expected_failed else {}
    expected_rows_set = set()
    for item in expected_failed:
        svc = item["service"]
        desc = item["description"]
        pe = expected_primary.get(svc)
        if pe is not None:
            expected_rows_set.add((svc, desc, pe))

    parsed_csv = _parse_csv(csv_out_path)
    if parsed_csv is not None:
        headers, rows = parsed_csv
        if headers == ["service", "description", "primary_error"]:
            scores["failed_services_csv_headers_correct"] = 1.0
        actual_set = set()
        for r in rows:
            actual_set.add((r.get("service", ""), r.get("description", ""), r.get("primary_error", "")))
        if expected_rows_set and len(rows) == len(expected_rows_set) and actual_set == expected_rows_set:
            scores["failed_services_csv_rows_match"] = 1.0

    expected_power = _compute_power_summary(power_samples_path)
    out_json = _load_json(json_out_path)
    required_fields = [
        "start_timestamp",
        "end_timestamp",
        "time_window_minutes",
        "start_battery_pct",
        "end_battery_pct",
        "net_drop_pct",
        "avg_drain_pct_per_hour",
        "mean_power_w",
        "min_power_w",
        "max_power_w",
        "est_hours_to_20pct_from_start",
    ]
    if isinstance(out_json, dict):
        all_present = all(k in out_json for k in required_fields)
        types_ok = True
        if all_present:
            if not isinstance(out_json.get("start_timestamp"), str):
                types_ok = False
            if not isinstance(out_json.get("end_timestamp"), str):
                types_ok = False
            num_keys = [k for k in required_fields if k not in ("start_timestamp", "end_timestamp")]
            for k in num_keys:
                if not isinstance(out_json.get(k), (int, float)):
                    types_ok = False
        if all_present and types_ok:
            scores["power_summary_json_fields_and_types"] = 1.0

    if expected_power is not None and isinstance(out_json, dict):
        tol = 1e-6
        values_ok = True
        try:
            if out_json.get("start_timestamp") != expected_power["start_timestamp"]:
                values_ok = False
            if out_json.get("end_timestamp") != expected_power["end_timestamp"]:
                values_ok = False
            for k in [
                "time_window_minutes",
                "start_battery_pct",
                "end_battery_pct",
                "net_drop_pct",
                "avg_drain_pct_per_hour",
                "mean_power_w",
                "min_power_w",
                "max_power_w",
                "est_hours_to_20pct_from_start",
            ]:
                if k not in out_json:
                    values_ok = False
                    break
                v = float(out_json[k])
                ev = float(expected_power[k])
                if not (abs(v - ev) <= tol):
                    values_ok = False
                    break
        except Exception:
            values_ok = False
        if values_ok:
            scores["power_summary_json_values_correct"] = 1.0

        try:
            start_b = float(out_json.get("start_battery_pct"))
            end_b = float(out_json.get("end_battery_pct"))
            net_drop = float(out_json.get("net_drop_pct"))
            tw = float(out_json.get("time_window_minutes"))
            st_ts = _parse_iso(out_json.get("start_timestamp"))
            en_ts = _parse_iso(out_json.get("end_timestamp"))
            valid = True
            if st_ts is None or en_ts is None:
                valid = False
            else:
                delta_min = (en_ts - st_ts).total_seconds() / 60.0
                if abs(delta_min - tw) > tol:
                    valid = False
            if abs((start_b - end_b) - net_drop) > tol:
                valid = False
            if valid:
                scores["power_summary_validation_consistency"] = 1.0
        except Exception:
            pass

    readme_text = _read_text(readme_path)
    if readme_text is not None:
        lines = readme_text.splitlines()
        audit_date = None
        if expected_power is not None:
            ts0 = expected_power["start_timestamp"]
            dt0 = _parse_iso(ts0)
            if dt0 is not None:
                audit_date = dt0.date().isoformat()
        expected_header = f"## Power Optimization Audit - {audit_date}" if audit_date else None

        header_ok = False
        date_ok = False
        old_header_absent = True
        if expected_header:
            start_idx, end_idx = _find_section(lines, expected_header)
            if start_idx != -1:
                header_ok = True
                date_ok = True
            for ln in lines:
                if ln.strip() == "## Power Optimization (TBD)":
                    old_header_absent = False
                    break

        if header_ok and date_ok and old_header_absent:
            scores["readme_header_replaced_and_date"] = 1.0

        if expected_header:
            start_idx, end_idx = _find_section(lines, expected_header)
            if start_idx != -1:
                section_lines = lines[start_idx + 1:end_idx]
                para_lines = []
                for ln in section_lines:
                    if not ln.strip():
                        if para_lines:
                            break
                        else:
                            continue
                    if ln.strip().startswith("-") or ln.strip().startswith("*") or ln.strip().startswith("## "):
                        if para_lines:
                            break
                        else:
                            continue
                    para_lines.append(ln.strip())
                if para_lines:
                    para_text = " ".join(para_lines)
                    n_sent = _count_sentences(para_text)
                    if 1 <= n_sent <= 3:
                        scores["readme_contains_paragraph_1_to_3_sentences"] = 1.0

        metrics_ok = False
        if expected_header and isinstance(out_json, dict):
            start_idx, end_idx = _find_section(lines, expected_header)
            if start_idx != -1:
                section_lines = lines[start_idx + 1:end_idx]
                bullet_lines = [ln for ln in section_lines if ln.strip().startswith("- ")]
                present_count = 0
                for key in [
                    "start_timestamp",
                    "end_timestamp",
                    "time_window_minutes",
                    "start_battery_pct",
                    "end_battery_pct",
                    "net_drop_pct",
                    "avg_drain_pct_per_hour",
                    "mean_power_w",
                    "min_power_w",
                    "max_power_w",
                    "est_hours_to_20pct_from_start",
                ]:
                    if key not in out_json:
                        continue
                    val = out_json[key]
                    if isinstance(val, (int, float)):
                        val_str = _json_number_string(val)
                    else:
                        val_str = str(val)
                    found = any((key in bl and val_str in bl) for bl in bullet_lines)
                    if found:
                        present_count += 1
                if present_count == 11:
                    metrics_ok = True
        if metrics_ok:
            scores["readme_metrics_bullets_match_json"] = 1.0

        failed_ok = False
        if expected_header:
            start_idx, end_idx = _find_section(lines, expected_header)
            if start_idx != -1:
                section_str = "\n".join(lines[start_idx + 1:end_idx])
                title_present = "Failed services" in section_str
                bullets = [ln for ln in lines[start_idx + 1:end_idx] if ln.strip().startswith("- ")]
                ok_count = 0
                parsed_csv_out = _parse_csv(csv_out_path)
                if title_present and parsed_csv_out is not None:
                    _, out_rows = parsed_csv_out
                    for r in out_rows:
                        svc = r.get("service", "")
                        pe = r.get("primary_error", "")
                        quoted_err = f"\"{pe}\""
                        match = any((svc in bl and quoted_err in bl) for bl in bullets)
                        if match:
                            ok_count += 1
                if title_present and parsed_csv_out is not None and ok_count == len(parsed_csv_out[1]) and ok_count > 0:
                    failed_ok = True
        if failed_ok:
            scores["readme_failed_services_listed_with_quotes"] = 1.0

        structure_ok = False
        top_title_present = any(ln.strip() == "# Laptop Ops Notes" for ln in lines)
        startup_section_present = any(ln.strip().startswith("## Startup Services") for ln in lines)
        old_header_absent2 = not any(ln.strip() == "## Power Optimization (TBD)" for ln in lines)
        if top_title_present and startup_section_present and old_header_absent2:
            structure_ok = True
        if structure_ok:
            scores["readme_structure_preserved_titles"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()