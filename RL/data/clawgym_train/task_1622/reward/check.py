import json
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_parse_iso_datetime(ts: str):
    try:
        return datetime.strptime(ts.strip(), "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def _parse_hhmm(s: str):
    if not isinstance(s, str):
        return None
    s = s.strip()
    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", s):
        h, m = s.split(":")
        return int(h), int(m)
    return None


def _compute_next_run_after(ref_dt: datetime, hhmm: str) -> str:
    parsed = _parse_hhmm(hhmm)
    if not parsed or not isinstance(ref_dt, datetime):
        return ""
    h, m = parsed
    candidate = ref_dt.replace(hour=h, minute=m, second=0, microsecond=0)
    if candidate <= ref_dt:
        candidate += timedelta(days=1)
    return candidate.strftime("%Y-%m-%d %H:%M")


def _simple_yaml_load(text: str):
    # Minimal YAML loader sufficient for the provided inputs:
    # - Mappings with indentation (2 spaces)
    # - Scalars: quoted/unquoted strings, booleans, integers
    lines = text.splitlines()
    root = {}
    stack = [(0, root)]
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if ":" not in content:
            return None
        key_part, val_part = content.split(":", 1)
        key = key_part.strip()
        val = val_part.strip()

        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if not isinstance(current, dict):
            return None

        if val == "":
            new_map = {}
            current[key] = new_map
            # Assume standard indent increment of 2 spaces
            stack.append((indent + 2, new_map))
        else:
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                parsed = val[1:-1]
            elif val.lower() in ("true", "false"):
                parsed = val.lower() == "true"
            else:
                try:
                    parsed = int(val)
                except Exception:
                    parsed = val
            current[key] = parsed
    return root


def _load_yaml_file(path: Path):
    text = _read_text(path)
    if not text:
        return None
    cfg = _simple_yaml_load(text)
    if not isinstance(cfg, dict):
        return None
    return cfg


def _get_last_completed_timestamp(log_path: Path) -> str:
    text = _read_text(log_path)
    if not text:
        return ""
    latest = None
    latest_str = ""
    for line in text.splitlines():
        if "Completed" in line:
            # Expect format: ISO_TIMESTAMP <space> Message
            parts = line.split(" ", 1)
            if not parts:
                continue
            ts = parts[0].strip()
            dt = _safe_parse_iso_datetime(ts)
            if dt is None:
                continue
            if latest is None or dt > latest:
                latest = dt
                latest_str = ts
    return latest_str


def _find_service_section(lines, service_name: str):
    # Attempt to find a section starting at a line mentioning the service name,
    # and ending before the next other service mention or end of file.
    indices = [i for i, ln in enumerate(lines) if service_name.lower() in ln.lower()]
    if not indices:
        return []
    candidates = []
    for start in indices:
        # determine next boundary: next occurrence of the other service or next header that mentions "service"
        end = len(lines)
        other = "weather_logger" if service_name == "watering" else "watering"
        for j in range(start + 1, len(lines)):
            if other.lower() in lines[j].lower():
                end = j
                break
        candidates.append(lines[start:end])
    # Choose the first candidate that appears to contain the required keys placeholders
    for sect in candidates:
        joined = "\n".join(sect).lower()
        if ("last_run" in joined) and ("schedule_time" in joined) and ("next_run_after_ref" in joined):
            return sect
    # Fallback to the first occurrence if no key-rich section found
    return candidates[0] if candidates else []


def _extract_field_value_from_section(section_lines, key_name: str) -> str:
    # Extract the text after "key_name:" in the section, first occurrence.
    key_lower = key_name.lower()
    for ln in section_lines:
        if ":" in ln:
            left, right = ln.split(":", 1)
            if left.strip().lower() == key_lower:
                return right.strip()
    # Fallback: search for lines that contain "key_name" and take text after colon if present
    for ln in section_lines:
        if key_lower in ln.lower() and ":" in ln:
            _, right = ln.split(":", 1)
            return right.strip()
    return ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "watering_enabled_key_fixed": 0.0,
        "watering_start_time_updated_to_08_45": 0.0,
        "report_exists": 0.0,
        "report_watering_section_valid": 0.0,
        "report_weather_section_valid": 0.0,
        "change_log_includes_start_time_edit": 0.0,
        "change_log_includes_enable_to_enabled": 0.0,
    }

    # Load configuration
    cfg_path = workspace / "input" / "garden_config.yaml"
    cfg = _load_yaml_file(cfg_path)
    services = cfg.get("services", {}) if isinstance(cfg, dict) else {}
    watering_cfg = services.get("watering", {}) if isinstance(services, dict) else {}
    weather_cfg = services.get("weather_logger", {}) if isinstance(services, dict) else {}

    # Check watering key fix: 'enabled' exists and 'enable' does not.
    if isinstance(watering_cfg, dict):
        has_enabled = "enabled" in watering_cfg and isinstance(watering_cfg.get("enabled"), bool)
        has_enable = "enable" in watering_cfg
        if has_enabled and not has_enable:
            scores["watering_enabled_key_fixed"] = 1.0

    # Check watering start_time updated to 08:45
    if isinstance(watering_cfg, dict):
        st = watering_cfg.get("start_time")
        if isinstance(st, str) and st.strip() == "08:45":
            scores["watering_start_time_updated_to_08_45"] = 1.0

    # Compute expected report values if possible
    # Enabled flags
    watering_enabled = None
    if isinstance(watering_cfg, dict) and isinstance(watering_cfg.get("enabled"), bool):
        watering_enabled = "true" if watering_cfg.get("enabled") else "false"

    weather_enabled = None
    if isinstance(weather_cfg, dict) and isinstance(weather_cfg.get("enabled"), bool):
        weather_enabled = "true" if weather_cfg.get("enabled") else "false"

    # Schedules
    watering_schedule = watering_cfg.get("start_time") if isinstance(watering_cfg, dict) else None
    weather_schedule = weather_cfg.get("schedule_time") if isinstance(weather_cfg, dict) else None

    # Last completed timestamps from logs
    watering_last = _get_last_completed_timestamp(workspace / "logs" / "watering.log")
    weather_last = _get_last_completed_timestamp(workspace / "logs" / "weather.log")

    # Reference datetime and next runs
    ref_text = _read_text(workspace / "input" / "reference_datetime.txt").strip()
    ref_dt = _safe_parse_iso_datetime(ref_text) if ref_text else None
    watering_next = _compute_next_run_after(ref_dt, watering_schedule) if (ref_dt and isinstance(watering_schedule, str)) else ""
    weather_next = _compute_next_run_after(ref_dt, weather_schedule) if (ref_dt and isinstance(weather_schedule, str)) else ""

    # Validate report
    report_path = workspace / "output" / "system_status.md"
    report_text = _read_text(report_path)
    if report_text:
        scores["report_exists"] = 1.0
        lines = report_text.splitlines()

        # Watering section validation
        wat_section = _find_service_section(lines, "watering")
        if wat_section and watering_enabled and watering_last and watering_schedule and watering_next:
            # Extract fields
            enabled_val = _extract_field_value_from_section(wat_section, "enabled").lower()
            last_run_val = _extract_field_value_from_section(wat_section, "last_run")
            sched_val = _extract_field_value_from_section(wat_section, "schedule_time")
            next_val = _extract_field_value_from_section(wat_section, "next_run_after_ref")
            if (enabled_val == watering_enabled.lower()
                and last_run_val == watering_last
                and sched_val == watering_schedule
                and next_val == watering_next):
                scores["report_watering_section_valid"] = 1.0

        # Weather section validation
        wea_section = _find_service_section(lines, "weather_logger")
        if wea_section and weather_enabled and weather_last and weather_schedule and weather_next:
            enabled_val = _extract_field_value_from_section(wea_section, "enabled").lower()
            last_run_val = _extract_field_value_from_section(wea_section, "last_run")
            sched_val = _extract_field_value_from_section(wea_section, "schedule_time")
            next_val = _extract_field_value_from_section(wea_section, "next_run_after_ref")
            if (enabled_val == weather_enabled.lower()
                and last_run_val == weather_last
                and sched_val == weather_schedule
                and next_val == weather_next):
                scores["report_weather_section_valid"] = 1.0

        # Change log validation: look for lines with "->" or "→"
        change_lines = [ln for ln in lines if ("->" in ln or "→" in ln)]
        if change_lines:
            # Start time change 06:45 -> 08:45
            st_ok = any(("start_time" in ln and "06:45" in ln and "08:45" in ln and ("->" in ln or "→" in ln)) for ln in change_lines)
            if st_ok:
                scores["change_log_includes_start_time_edit"] = 1.0
            # enable -> enabled key fix
            en_ok = any(("enable" in ln and "enabled" in ln and ("->" in ln or "→" in ln)) for ln in change_lines)
            if en_ok:
                scores["change_log_includes_enable_to_enabled"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()