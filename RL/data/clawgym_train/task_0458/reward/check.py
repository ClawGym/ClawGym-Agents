import json
import sys
import re
from pathlib import Path
from datetime import datetime, time
from typing import Optional, Tuple, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _strip_inline_comment(line: str) -> str:
    # Remove inline comments (# ...) when not inside double quotes
    result = []
    in_quote = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == '"':
            in_quote = not in_quote
            result.append(c)
        elif c == '#' and not in_quote:
            break
        else:
            result.append(c)
        i += 1
    return "".join(result).rstrip("\n").rstrip()


def _parse_simple_yaml_config(text: str) -> Optional[Dict[str, Any]]:
    # Minimal parser tailored to given schema
    lines = text.splitlines()
    cleaned = []
    for raw in lines:
        stripped = _strip_inline_comment(raw)
        if stripped.strip() == "":
            continue
        cleaned.append(stripped)

    cfg: Dict[str, Any] = {}
    i = 0
    n = len(cleaned)
    while i < n:
        line = cleaned[i]
        m_sec = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*$', line)
        m_scalar = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$', line)
        if m_sec:
            key = m_sec.group(1)
            i += 1
            section: Dict[str, Any] = {}
            while i < n:
                subline = cleaned[i]
                if re.match(r'^\S', subline):
                    break
                m_kv = re.match(r'^\s+([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$', subline)
                if m_kv:
                    skey, sval = m_kv.group(1), m_kv.group(2)
                    sval = sval.strip()
                    if sval.startswith('"') and sval.endswith('"') and len(sval) >= 2:
                        sval = sval[1:-1]
                    elif re.match(r'^\d+$', sval):
                        try:
                            sval = int(sval)
                        except Exception:
                            pass
                    section[skey] = sval
                i += 1
            cfg[key] = section
            continue
        elif m_scalar:
            key, val = m_scalar.group(1), m_scalar.group(2).strip()
            if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                val = val[1:-1]
            elif re.match(r'^\d+$', val):
                try:
                    val = int(val)
                except Exception:
                    pass
            cfg[key] = val
        i += 1

    if "quiet_hours" not in cfg or not isinstance(cfg["quiet_hours"], dict):
        return None
    qh = cfg["quiet_hours"]
    if "start" not in qh or "end" not in qh:
        return None
    if "threshold_db" not in cfg:
        return None
    if "neighborhood" not in cfg:
        return None
    return cfg


def _parse_noise_log(path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text(path)
    if text is None:
        return None
    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != 4:
            return None
        ts_s, location, decibel_s, source = [p.strip() for p in parts]
        try:
            dt = datetime.strptime(ts_s, "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return None
        try:
            decibel = int(decibel_s)
        except Exception:
            return None
        events.append({
            "timestamp": ts_s,
            "datetime": dt,
            "date": dt.date().isoformat(),
            "time": dt.time().strftime("%H:%M:%S"),
            "location": location,
            "decibel": decibel,
            "source": source,
        })
    return events


def _hhmm_to_minutes(hhmm: str) -> Optional[int]:
    m = re.match(r'^(\d{2}):(\d{2})$', hhmm)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    return h * 60 + mi


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _within_quiet_hours(dt: datetime, start_hhmm: str, end_hhmm: str) -> Optional[bool]:
    sm = _hhmm_to_minutes(start_hhmm)
    em = _hhmm_to_minutes(end_hhmm)
    if sm is None or em is None:
        return None
    tm = _time_to_minutes(dt.time())
    if sm < em:
        return sm <= tm < em
    else:
        # Crosses midnight
        return tm >= sm or tm < em


def _parse_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text(path)
    if text is None:
        return None
    recs: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line == "":
            continue
        try:
            obj = json.loads(line)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        recs.append(obj)
    return recs


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _find_nested_config_in_status(status: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for _, v in status.items():
        if isinstance(v, dict):
            if ("quiet_hours" in v and isinstance(v["quiet_hours"], dict)
                and "start" in v["quiet_hours"] and "end" in v["quiet_hours"]
                and "threshold_db" in v and "neighborhood" in v):
                return v
    return None


def _find_section_block(lines: List[str], section_name: str) -> Tuple[Optional[int], Optional[int]]:
    start_idx = None
    for idx, ln in enumerate(lines):
        if re.match(r'^\s*#+\s*', ln):
            if re.search(re.escape(section_name), ln, re.IGNORECASE):
                start_idx = idx
                break
        else:
            if ln.strip().lower() == section_name.lower():
                start_idx = idx
                break
    if start_idx is None:
        return None, None
    next_idx = None
    for idx in range(start_idx + 1, len(lines)):
        ln = lines[idx]
        if re.match(r'^\s*#+\s*.+$', ln):
            next_idx = idx
            break
    if next_idx is None:
        next_idx = len(lines)
    return start_idx, next_idx


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "threshold_set_to_55": 0.0,
        "violations_file_parseable": 0.0,
        "violations_count_and_order": 0.0,
        "violations_fields_and_values": 0.0,
        "violations_no_duplicates": 0.0,
        "status_json_valid": 0.0,
        "status_counts_and_last_timestamp_correct": 0.0,
        "status_includes_config_copy": 0.0,
        "daily_summary_opening_line": 0.0,
        "daily_summary_by_date_correct": 0.0,
        "daily_summary_top_sources": 0.0,
        "state_file_present": 0.0,
    }

    # Paths
    config_path = workspace / "config" / "settings.yaml"
    log_path = workspace / "input" / "noise_events.log"
    violations_path = workspace / "output" / "violations.jsonl"
    status_path = workspace / "output" / "status.json"
    summary_path = workspace / "output" / "daily_summary.md"
    output_dir = workspace / "output"

    # Parse config
    cfg_text = _read_text(config_path)
    cfg = None
    if cfg_text is not None:
        cfg = _parse_simple_yaml_config(cfg_text)
    if cfg is not None:
        try:
            if int(cfg.get("threshold_db")) == 55:
                scores["threshold_set_to_55"] = 1.0
        except Exception:
            pass

    # Parse log and compute expected results
    events = _parse_noise_log(log_path)
    expected_violations: List[Dict[str, Any]] = []
    expected_processed_total = 0
    expected_last_ts = None
    if events is not None:
        expected_processed_total = len(events)
        if expected_processed_total > 0:
            expected_last_ts = events[-1]["timestamp"]
        # Compute expected violations for threshold 55, quiet hours 21:30–07:00 UTC
        for ev in events:
            within = _within_quiet_hours(ev["datetime"], "21:30", "07:00")
            if within is None:
                continue
            if within and ev["decibel"] >= 55:
                expected_violations.append(ev)

    # Violations JSONL checks
    violations = _parse_jsonl(violations_path)
    if violations is not None:
        scores["violations_file_parseable"] = 1.0
        # Count and order
        expected_ts_order = [ev["timestamp"] for ev in expected_violations]
        actual_ts_order = [v.get("timestamp") for v in violations]
        if len(violations) == len(expected_ts_order) == 6 and actual_ts_order == expected_ts_order:
            scores["violations_count_and_order"] = 1.0
        # Fields and values
        fields_ok = True
        if len(violations) != len(expected_violations):
            fields_ok = False
        else:
            for v, ev in zip(violations, expected_violations):
                try:
                    req_fields = [
                        "timestamp", "date", "time", "location",
                        "decibel", "source", "threshold_db",
                        "within_quiet_hours", "classification"
                    ]
                    for f in req_fields:
                        if f not in v:
                            fields_ok = False
                            break
                    if not fields_ok:
                        break
                    if v["timestamp"] != ev["timestamp"]:
                        fields_ok = False
                        break
                    if v["date"] != ev["date"]:
                        fields_ok = False
                        break
                    if v["time"] != ev["time"]:
                        fields_ok = False
                        break
                    if v["location"] != ev["location"]:
                        fields_ok = False
                        break
                    if not isinstance(v["decibel"], int) or v["decibel"] != ev["decibel"]:
                        fields_ok = False
                        break
                    if v["source"] != ev["source"]:
                        fields_ok = False
                        break
                    if not isinstance(v["threshold_db"], int) or v["threshold_db"] != 55:
                        fields_ok = False
                        break
                    if not isinstance(v["within_quiet_hours"], bool) or v["within_quiet_hours"] is not True:
                        fields_ok = False
                        break
                    if v["classification"] != "quiet_hours_violation":
                        fields_ok = False
                        break
                except Exception:
                    fields_ok = False
                    break
        if fields_ok and len(violations) == len(expected_violations) == 6:
            scores["violations_fields_and_values"] = 1.0
        # No duplicates (by timestamp)
        if len(set(actual_ts_order)) == len(actual_ts_order) and len(actual_ts_order) == 6:
            scores["violations_no_duplicates"] = 1.0

    # Status JSON checks
    status = _load_json(status_path)
    if status is not None and isinstance(status, dict):
        scores["status_json_valid"] = 1.0
        counts_ok = True
        try:
            if expected_processed_total > 0:
                if int(status.get("processed_events_total", -1)) != expected_processed_total:
                    counts_ok = False
                if int(status.get("violations_total", -1)) != 6:
                    counts_ok = False
                if status.get("last_processed_timestamp") != expected_last_ts:
                    counts_ok = False
            else:
                counts_ok = False
        except Exception:
            counts_ok = False
        if counts_ok:
            scores["status_counts_and_last_timestamp_correct"] = 1.0
        # Nested configuration copy present and correct values
        nested_cfg = _find_nested_config_in_status(status)
        nested_ok = False
        if nested_cfg is not None:
            try:
                qh = nested_cfg.get("quiet_hours", {})
                if (isinstance(qh, dict)
                        and str(qh.get("start")) == "21:30"
                        and str(qh.get("end")) == "07:00"
                        and int(nested_cfg.get("threshold_db")) == 55
                        and isinstance(nested_cfg.get("neighborhood"), str)
                        and nested_cfg.get("neighborhood") == "Grosvenor Square"):
                    nested_ok = True
            except Exception:
                nested_ok = False
        if nested_ok:
            scores["status_includes_config_copy"] = 1.0

    # Daily summary markdown checks
    summary_text = _read_text(summary_path)
    if summary_text is not None:
        lines = summary_text.splitlines()
        # Opening line: neighborhood and quiet hours window (UTC)
        first_nonempty = ""
        for ln in lines:
            if ln.strip():
                first_nonempty = ln
                break
        opening_ok = False
        if first_nonempty:
            if ("Grosvenor Square" in first_nonempty
                and "21:30" in first_nonempty
                and "07:00" in first_nonempty
                and re.search(r'\bUTC\b', first_nonempty, flags=re.IGNORECASE)):
                opening_ok = True
        if opening_ok:
            scores["daily_summary_opening_line"] = 1.0

        # By date (UTC) section correctness
        bydate_ok = False
        start_b, end_b = _find_section_block(lines, "By date (UTC)")
        if start_b is not None:
            by_block_lines = lines[start_b:end_b]
            per_date: Dict[str, Dict[str, Any]] = {}
            for ev in expected_violations:
                d = ev["date"]
                if d not in per_date:
                    per_date[d] = {"count": 0, "max_db": None}
                per_date[d]["count"] += 1
                if per_date[d]["max_db"] is None or ev["decibel"] > per_date[d]["max_db"]:
                    per_date[d]["max_db"] = ev["decibel"]
            found_all = True
            for d, stats in per_date.items():
                found_line = False
                for ln in by_block_lines:
                    if d in ln:
                        ln_wo_date = ln.replace(d, "")
                        nums = [int(x) for x in re.findall(r'\b\d+\b', ln_wo_date)]
                        if stats["count"] in nums and stats["max_db"] in nums:
                            found_line = True
                            break
                if not found_line:
                    found_all = False
                    break
            bydate_ok = found_all and len(per_date) > 0
        if bydate_ok:
            scores["daily_summary_by_date_correct"] = 1.0

        # Top sources section
        start_t, end_t = _find_section_block(lines, "Top sources")
        tops_ok = False
        if start_t is not None:
            top_block = "\n".join(lines[start_t:end_t])
            known_sources = {"revving_motorbike", "loud_chatting", "clattering_bins", "radio_music", "door_slams", "bird_scarer"}
            present = set()
            for s in known_sources:
                if s in top_block:
                    present.add(s)
            if len(present) >= 3:
                tops_ok = True
        if tops_ok:
            scores["daily_summary_top_sources"] = 1.0

    # State file presence: any file in output/ other than the three expected outputs
    state_ok = False
    try:
        if output_dir.exists() and output_dir.is_dir():
            for p in output_dir.iterdir():
                if p.is_file() and p.name not in {"violations.jsonl", "status.json", "daily_summary.md"}:
                    state_ok = True
                    break
    except Exception:
        state_ok = False
    if state_ok:
        scores["state_file_present"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
            workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()