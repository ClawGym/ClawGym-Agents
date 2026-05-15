import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, f"read_error:{e}"


def _load_json_safe(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None, "json_not_object"
        return data, None
    except Exception as e:
        return None, f"json_error:{e}"


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_rules_yaml(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """
    Minimal YAML parser tailored to the expected structure of config/rules.yaml:
    - quiet_hours:
        start: "HH:MM"
        end: "HH:MM"
    - restricted_zones:
        - id: "zone_id"
          name: "..."
          lat_min: float
          lat_max: float
          lon_min: float
          lon_max: float
    - do_not_shoot_subjects:
        - "Subject"
        - "Another"
    """
    text, err = _read_text_safe(path)
    if err or text is None:
        return None, err or "missing_yaml"
    lines = text.splitlines()
    section = None
    rules: Dict[str, Any] = {}
    zones: List[Dict[str, Any]] = []
    zone_current: Optional[Dict[str, Any]] = None
    subjects: List[str] = []
    quiet: Dict[str, str] = {}

    def flush_zone():
        nonlocal zone_current
        if zone_current is not None and zone_current:
            zones.append(zone_current)
        zone_current = None

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if re.match(r"^\s*#", line):
            continue

        m_top = re.match(r"^([A-Za-z0-9_]+):\s*$", line)
        if m_top:
            if section == "restricted_zones":
                flush_zone()
            section = m_top.group(1)
            continue

        if section == "quiet_hours":
            m = re.match(r"^\s{2}([a-zA-Z0-9_]+):\s*(.+?)\s*$", line)
            if m:
                key = m.group(1)
                val = _strip_quotes(m.group(2))
                quiet[key] = val
            else:
                return None, "yaml_parse_error_quiet_hours"
        elif section == "restricted_zones":
            if re.match(r"^\s{2}-\s", line):
                flush_zone()
                zone_current = {}
                m = re.match(r"^\s{2}-\s*([a-zA-Z0-9_]+):\s*(.+?)\s*$", line)
                if m:
                    k = m.group(1)
                    v = _strip_quotes(m.group(2))
                    if k in ("lat_min", "lat_max", "lon_min", "lon_max"):
                        fv = _parse_float(v)
                        if fv is None:
                            return None, "yaml_parse_error_zone_numeric"
                        zone_current[k] = fv
                    else:
                        zone_current[k] = v
                continue
            mprop = re.match(r"^\s{4}([a-zA-Z0-9_]+):\s*(.+?)\s*$", line)
            if mprop:
                if zone_current is None:
                    zone_current = {}
                k = mprop.group(1)
                v = _strip_quotes(mprop.group(2))
                if k in ("lat_min", "lat_max", "lon_min", "lon_max"):
                    fv = _parse_float(v)
                    if fv is None:
                        return None, "yaml_parse_error_zone_numeric"
                    zone_current[k] = fv
                else:
                    zone_current[k] = v
            else:
                return None, "yaml_parse_error_zones"
        elif section == "do_not_shoot_subjects":
            m = re.match(r"^\s{2}-\s*(.+?)\s*$", line)
            if m:
                subjects.append(_strip_quotes(m.group(1)))
            else:
                return None, "yaml_parse_error_subjects"
        else:
            continue

    if section == "restricted_zones":
        flush_zone()

    if quiet:
        if "start" not in quiet or "end" not in quiet:
            return None, "yaml_quiet_hours_missing"
        rules["quiet_hours"] = {"start": quiet["start"], "end": quiet["end"]}
    if zones:
        rules["restricted_zones"] = zones
    if subjects:
        rules["do_not_shoot_subjects"] = subjects

    if "quiet_hours" not in rules or "restricted_zones" not in rules or "do_not_shoot_subjects" not in rules:
        return None, "yaml_missing_required_sections"

    return rules, None


def _parse_time_hhmm(s: str) -> Optional[time]:
    m = re.match(r"^\s*(\d{2}):(\d{2})\s*$", s)
    if not m:
        return None
    try:
        hh = int(m.group(1))
        mm = int(m.group(2))
        return time(hh, mm, 0)
    except Exception:
        return None


def _parse_captured_time_of_day(captured_at: str) -> Optional[time]:
    m = re.search(r"T(\d{2}):(\d{2}):(\d{2})", captured_at)
    if not m:
        try:
            dt = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            return time(dt.hour, dt.minute, dt.second)
        except Exception:
            return None
    try:
        hh = int(m.group(1))
        mm = int(m.group(2))
        ss = int(m.group(3))
        return time(hh, mm, ss)
    except Exception:
        return None


def _time_in_interval(t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= t < end
    else:
        return t >= start or t < end


def _compute_triggers(meta: dict, rules: dict) -> Tuple[List[str], Optional[str]]:
    if not isinstance(meta, dict):
        return ["invalid"], "meta_not_dict"

    required_error = None
    if "file_name" not in meta or not isinstance(meta["file_name"], str):
        required_error = "missing_file_name"
    if "captured_at" not in meta or not isinstance(meta["captured_at"], str):
        required_error = "missing_captured_at"
    gps = meta.get("gps")
    lat = lon = None
    if not isinstance(gps, dict):
        required_error = "missing_gps"
    else:
        lat = gps.get("lat")
        lon = gps.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            required_error = "gps_lat_lon_invalid"
    subjects = meta.get("subjects")
    if not isinstance(subjects, list):
        required_error = "subjects_invalid"

    if required_error:
        return ["invalid"], required_error

    triggers: List[str] = []

    zones = rules.get("restricted_zones", [])
    for z in zones:
        try:
            if (
                z.get("lat_min") is not None
                and z.get("lat_max") is not None
                and z.get("lon_min") is not None
                and z.get("lon_max") is not None
            ):
                if (z["lat_min"] <= lat <= z["lat_max"]) and (z["lon_min"] <= lon <= z["lon_max"]):
                    zid = z.get("id")
                    if isinstance(zid, str) and zid:
                        triggers.append(zid)
        except Exception:
            continue

    qh = rules.get("quiet_hours", {})
    start_s = qh.get("start")
    end_s = qh.get("end")
    t = _parse_captured_time_of_day(meta["captured_at"])
    ts = _parse_time_hhmm(start_s) if isinstance(start_s, str) else None
    te = _parse_time_hhmm(end_s) if isinstance(end_s, str) else None
    if t and ts and te:
        if _time_in_interval(t, ts, te):
            triggers.append("quiet_hours")

    deny_subjects = set(rules.get("do_not_shoot_subjects", []))
    if isinstance(subjects, list):
        for s in subjects:
            if isinstance(s, str) and s in deny_subjects:
                triggers.append(f"subject:{s}")

    return triggers, None


def _is_iso_datetime(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "details_files_present": 0.0,
        "details_content_correct": 0.0,
        "csv_exists_and_header": 0.0,
        "csv_rows_correct": 0.0,
        "csv_processed_at_iso_format": 0.0,
        "summary_counts_correct": 0.0,
        "no_duplicate_processing": 0.0,
    }

    rules_path = workspace / "config" / "rules.yaml"
    rules, rules_err = _parse_rules_yaml(rules_path)
    if not rules or rules_err:
        # Without rules we cannot compute expected outcomes; keep zeros.
        return scores

    input_queue_dir = workspace / "input" / "queue"
    expected_files: List[Path] = []
    if input_queue_dir.exists() and input_queue_dir.is_dir():
        expected_files = sorted([p for p in input_queue_dir.glob("*.json") if p.is_file()])
    if not expected_files:
        return scores

    expected_map: Dict[str, Dict[str, Any]] = {}
    for p in expected_files:
        data, err = _load_json_safe(p)
        if err or data is None:
            continue
        base = p.stem
        triggers, invalid_err = _compute_triggers(data, rules)
        if invalid_err is not None:
            status = "invalid"
            triggers = ["invalid"]
        else:
            status = "sensitive" if len(triggers) > 0 else "ok"
        gps = data.get("gps") if isinstance(data.get("gps"), dict) else {}
        expected_map[base] = {
            "detail_path": workspace / "reports" / "details" / f"{base}.decision.json",
            "file_name": data.get("file_name"),
            "captured_at": data.get("captured_at"),
            "lat": gps.get("lat"),
            "lon": gps.get("lon"),
            "subjects": data.get("subjects"),
            "triggers": sorted(triggers),
            "status": status,
        }

    if not expected_map:
        return scores

    present_count = 0
    correct_count = 0
    for base, exp in expected_map.items():
        dpath: Path = exp["detail_path"]
        if dpath.exists() and dpath.is_file():
            present_count += 1
            detail_data, derr = _load_json_safe(dpath)
            if derr or detail_data is None:
                continue
            req_keys = ["file_name", "status", "triggers", "captured_at", "gps", "subjects"]
            if not all(k in detail_data for k in req_keys):
                continue
            try:
                if detail_data["file_name"] != exp["file_name"]:
                    continue
                if detail_data["status"] != exp["status"]:
                    continue
                d_triggers = detail_data["triggers"]
                if not isinstance(d_triggers, list):
                    continue
                if sorted(list(d_triggers)) != sorted(exp["triggers"]):
                    continue
                if detail_data["captured_at"] != exp["captured_at"]:
                    continue
                gps = detail_data["gps"]
                if not isinstance(gps, dict):
                    continue
                dlat = gps.get("lat")
                dlon = gps.get("lon")
                if not isinstance(dlat, (int, float)) or not isinstance(dlon, (int, float)):
                    continue
                if exp["lat"] is None or exp["lon"] is None:
                    continue
                if abs(float(dlat) - float(exp["lat"])) > 1e-6 or abs(float(dlon) - float(exp["lon"])) > 1e-6:
                    continue
                if detail_data["subjects"] != exp["subjects"]:
                    continue
                correct_count += 1
            except Exception:
                continue
    total_expected = len(expected_map)
    scores["details_files_present"] = present_count / total_expected if total_expected > 0 else 0.0
    scores["details_content_correct"] = correct_count / total_expected if total_expected > 0 else 0.0

    detections_csv = workspace / "reports" / "detections.csv"
    header_ok = False
    rows: List[Dict[str, str]] = []
    if detections_csv.exists():
        try:
            with detections_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                all_rows = [row for row in reader if any(cell.strip() for cell in row)]
            if all_rows:
                header = all_rows[0]
                expected_header = ["processed_at", "file_name", "status", "triggers_joined", "lat", "lon"]
                if header == expected_header:
                    header_ok = True
                    for row in all_rows[1:]:
                        if len(row) != len(expected_header):
                            continue
                        rows.append(dict(zip(expected_header, row)))
        except Exception:
            header_ok = False
    scores["csv_exists_and_header"] = 1.0 if header_ok else 0.0

    csv_correct = 0
    iso_ok_count = 0
    duplicates_present = False
    if header_ok:
        seen_files: Dict[str, int] = {}
        for r in rows:
            fname = r.get("file_name", "")
            if fname:
                seen_files[fname] = seen_files.get(fname, 0) + 1
        if any(count > 1 for count in seen_files.values()):
            duplicates_present = True

        for base, exp in expected_map.items():
            # Match by exact file_name from metadata (strict as per requirements)
            matching = [r for r in rows if r.get("file_name") == exp.get("file_name")]
            if len(matching) != 1:
                continue
            r = matching[0]
            try:
                if r.get("status") != exp["status"]:
                    continue
                tj = r.get("triggers_joined", "")
                tokens = [t for t in [tok.strip() for tok in tj.split(";")] if t]
                if sorted(tokens) != sorted(exp["triggers"]):
                    continue
                rlat = _parse_float(r.get("lat", ""))
                rlon = _parse_float(r.get("lon", ""))
                if rlat is None or rlon is None:
                    continue
                if exp["lat"] is None or exp["lon"] is None:
                    continue
                if abs(rlat - float(exp["lat"])) > 1e-6 or abs(rlon - float(exp["lon"])) > 1e-6:
                    continue
                if _is_iso_datetime(r.get("processed_at", "")):
                    iso_ok_count += 1
                csv_correct += 1
            except Exception:
                continue

    scores["csv_rows_correct"] = csv_correct / total_expected if total_expected > 0 else 0.0
    scores["csv_processed_at_iso_format"] = iso_ok_count / total_expected if total_expected > 0 else 0.0
    scores["no_duplicate_processing"] = 0.0 if duplicates_present else (1.0 if header_ok else 0.0)

    summary_path = workspace / "reports" / "summary.json"
    summary_ok = 0.0
    if summary_path.exists():
        sdata, serr = _load_json_safe(summary_path)
        if not serr and isinstance(sdata, dict):
            total_expected_count = total_expected
            sensitive_count = sum(1 for v in expected_map.values() if v["status"] == "sensitive")
            ok_count = sum(1 for v in expected_map.values() if v["status"] == "ok")
            invalid_count = sum(1 for v in expected_map.values() if v["status"] == "invalid")
            try:
                if (
                    sdata.get("total_processed") == total_expected_count
                    and sdata.get("sensitive") == sensitive_count
                    and sdata.get("ok") == ok_count
                    and sdata.get("invalid") == invalid_count
                ):
                    summary_ok = 1.0
            except Exception:
                summary_ok = 0.0
    scores["summary_counts_correct"] = summary_ok

    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()