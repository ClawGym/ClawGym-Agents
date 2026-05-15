import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime, timezone


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_jsonl(path: Path):
    """
    Returns (records, ok). If any line fails to parse as JSON object, ok=False.
    """
    if not path.exists():
        return [], False
    records = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if line == "":
                    continue
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        return [], False
                    records.append(obj)
                except Exception:
                    return [], False
    except Exception:
        return [], False
    return records, True


def _parse_iso_ts(ts_str: str):
    """
    Parse ISO timestamp possibly ending with Z into aware datetime.
    Return None if parse fails.
    """
    if not isinstance(ts_str, str):
        return None
    s = ts_str
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _isoformat_z(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _compute_expected_from_logs(log_path: Path):
    """
    Compute expected outputs for:
      - disconnect_rank: list of [reason, count, distinct_devices, first_seen, last_seen]
      - frequent_offenders: list of [device_id, disconnects]
    Returns (disconnect_rank_rows, frequent_offenders_rows, ok)
    """
    events, ok = _parse_jsonl(log_path)
    if not ok:
        return [], [], False

    disconnects = []
    for ev in events:
        if ev.get("event_type") == "disconnect":
            ts = _parse_iso_ts(ev.get("ts"))
            reason = ev.get("reason")
            device_id = ev.get("device_id")
            if ts is None or reason is None or device_id is None:
                return [], [], False
            disconnects.append({"ts": ts, "reason": reason, "device_id": device_id})

    # Group by reason
    reason_map = {}
    for d in disconnects:
        r = d["reason"]
        if r not in reason_map:
            reason_map[r] = {
                "count": 0,
                "devices": set(),
                "first": None,
                "last": None,
            }
        rec = reason_map[r]
        rec["count"] += 1
        rec["devices"].add(d["device_id"])
        if rec["first"] is None or d["ts"] < rec["first"]:
            rec["first"] = d["ts"]
        if rec["last"] is None or d["ts"] > rec["last"]:
            rec["last"] = d["ts"]

    disconnect_rank_rows = []
    for r, rec in reason_map.items():
        disconnect_rank_rows.append([
            r,
            str(rec["count"]),
            str(len(rec["devices"])),
            _isoformat_z(rec["first"]),
            _isoformat_z(rec["last"]),
        ])
    # Sort by count DESC (numeric), then reason ASC
    disconnect_rank_rows.sort(key=lambda x: (-int(x[1]), x[0]))

    # Frequent offenders by device_id
    device_counts = {}
    for d in disconnects:
        device_counts[d["device_id"]] = device_counts.get(d["device_id"], 0) + 1

    frequent_offenders_rows = []
    for dev, cnt in device_counts.items():
        frequent_offenders_rows.append([dev, str(cnt)])
    # Sort by disconnects DESC then device_id ASC
    frequent_offenders_rows.sort(key=lambda x: (-int(x[1]), x[0]))

    return disconnect_rank_rows, frequent_offenders_rows, True


def _read_csv(path: Path):
    """
    Returns (header_list, rows_list, ok)
    """
    if not path.exists():
        return [], [], False
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return [], [], False
        header = rows[0]
        data_rows = rows[1:]
        return header, data_rows, True
    except Exception:
        return [], [], False


def _find_timeout_function_name(controller_js_path: Path):
    """
    Find the function name in src/controller.js that uses disconnectAfterMs.
    Strategy: find line(s) containing 'disconnectAfterMs', then scan upwards
    to the nearest preceding 'function <name>(' and return that <name>.
    Return None if not found or errors.
    """
    text = _read_text(controller_js_path)
    if text is None:
        return None
    lines = text.splitlines()
    target_indices = [i for i, ln in enumerate(lines) if "disconnectAfterMs" in ln]
    if not target_indices:
        return None
    func_name = None
    for idx in target_indices:
        j = idx
        while j >= 0:
            ln = lines[j]
            m = re.search(r'\bfunction\s+([A-Za-z0-9_]+)\s*\(', ln)
            if m:
                func_name = m.group(1)
                break
            j -= 1
        if func_name:
            break
    return func_name


def _compute_expected_config(config_path: Path, controller_js_path: Path):
    cfg = _load_json(config_path)
    if cfg is None:
        return None, False
    try:
        hb = cfg["network"]["heartbeatIntervalMs"]
        da = cfg["network"]["disconnectAfterMs"]
        if not isinstance(hb, (int, float)) or not isinstance(da, (int, float)):
            return None, False
        hb_num = int(hb)
        da_num = int(da)
    except Exception:
        return None, False
    func_name = _find_timeout_function_name(controller_js_path)
    if func_name is None:
        return None, False
    expected = {
        "heartbeatIntervalMs": hb_num,
        "disconnectAfterMs": da_num,
        "disconnect_after_lt_heartbeat": da_num < hb_num,
        "timeoutFunctionName": func_name,
    }
    return expected, True


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "disconnect_rank_correct": 0.0,
        "frequent_offenders_correct": 0.0,
        "config_check_correct": 0.0,
        "incident_report_correct": 0.0,
    }

    # Paths
    logs_path = workspace / "input" / "logs" / "controller_events.jsonl"
    config_path = workspace / "input" / "config" / "robot-config.json"
    controller_js_path = workspace / "src" / "controller.js"
    template_path = workspace / "docs" / "incident_report_template.md"

    out_disconnect_rank_path = workspace / "outputs" / "analysis" / "disconnect_rank.csv"
    out_frequent_offenders_path = workspace / "outputs" / "analysis" / "frequent_offenders.csv"
    out_config_check_path = workspace / "outputs" / "analysis" / "config_check.json"
    out_report_path = workspace / "outputs" / "report" / "incident_report.md"

    # Compute expected from logs
    exp_rank_rows, exp_off_rows, ok_logs = _compute_expected_from_logs(logs_path)

    # Check disconnect_rank.csv
    header, rows, ok_csv = _read_csv(out_disconnect_rank_path)
    if ok_logs and ok_csv:
        expected_header = ["reason", "count", "distinct_devices", "first_seen", "last_seen"]
        if header == expected_header and rows == exp_rank_rows:
            scores["disconnect_rank_correct"] = 1.0

    # Check frequent_offenders.csv
    header2, rows2, ok_csv2 = _read_csv(out_frequent_offenders_path)
    if ok_logs and ok_csv2:
        expected_header2 = ["device_id", "disconnects"]
        if header2 == expected_header2 and rows2 == exp_off_rows:
            scores["frequent_offenders_correct"] = 1.0

    # Compute expected config info
    expected_config, ok_cfg = _compute_expected_config(config_path, controller_js_path)

    # Check config_check.json
    actual_cfg = _load_json(out_config_check_path)
    if ok_cfg and isinstance(actual_cfg, dict):
        try:
            hb_val = actual_cfg.get("heartbeatIntervalMs", None)
            da_val = actual_cfg.get("disconnectAfterMs", None)
            lt_val = actual_cfg.get("disconnect_after_lt_heartbeat", None)
            fn_val = actual_cfg.get("timeoutFunctionName", None)

            # Numeric equality (accept int or float representing same values)
            hb_ok = isinstance(hb_val, (int, float)) and int(hb_val) == expected_config["heartbeatIntervalMs"]
            da_ok = isinstance(da_val, (int, float)) and int(da_val) == expected_config["disconnectAfterMs"]
            lt_ok = isinstance(lt_val, bool) and lt_val == expected_config["disconnect_after_lt_heartbeat"]
            fn_ok = isinstance(fn_val, str) and fn_val == expected_config["timeoutFunctionName"]

            if hb_ok and da_ok and lt_ok and fn_ok:
                scores["config_check_correct"] = 1.0
        except Exception:
            pass

    # Check incident_report.md by reconstructing expected filled template
    tmpl_text = _read_text(template_path)
    report_text = _read_text(out_report_path)
    if ok_logs and ok_cfg and tmpl_text is not None and report_text is not None:
        replacements = {
            "{{TOP_REASON}}": exp_rank_rows[0][0] if exp_rank_rows else "",
            "{{TOP_REASON_COUNT}}": exp_rank_rows[0][1] if exp_rank_rows else "",
            "{{TOP_DEVICE}}": exp_off_rows[0][0] if exp_off_rows else "",
            "{{TOP_DEVICE_COUNT}}": exp_off_rows[0][1] if exp_off_rows else "",
            "{{CONFIG_HEARTBEAT_MS}}": str(expected_config["heartbeatIntervalMs"]),
            "{{CONFIG_DISCONNECT_MS}}": str(expected_config["disconnectAfterMs"]),
            "{{TIMEOUT_FUNCTION_NAME}}": expected_config["timeoutFunctionName"],
        }
        expected_report = tmpl_text
        for k, v in replacements.items():
            expected_report = expected_report.replace(k, v)
        if _normalize_newlines(expected_report) == _normalize_newlines(report_text):
            scores["incident_report_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()