import json
import re
import sys
from pathlib import Path


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _split_maybe_escaped_lines(text: str):
    if text is None:
        return []
    text_norm = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text_norm.split("\n")
    if len(lines) <= 1 and "\\n" in text_norm:
        parts = text_norm.split("\\n")
        if parts and parts[-1] == "":
            parts = parts[:-1]
        return parts
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def _find_address_in_use_line(lines, host=None, port=None):
    if not lines:
        return None
    for ln in lines:
        if "Address already in use" in ln and "OSError" in ln:
            if host is not None and str(host) not in ln:
                continue
            if port is not None and str(port) not in ln:
                continue
            return ln
    for ln in lines:
        if "ERROR" in ln and "OSError" in ln:
            if host is not None and str(host) not in ln:
                continue
            if port is not None and str(port) not in ln:
                continue
            return ln
    return None


def _find_serving_line(lines):
    if not lines:
        return None
    for ln in lines:
        if ln.startswith("Serving setlist viewer on"):
            return ln
    return None


def _parse_incident_sections(md_text: str):
    sections = {"root_cause": "", "command_output": "", "fix": "", "verification": ""}
    current = None
    if md_text is None:
        return sections
    lines = md_text.splitlines()
    section_pattern = re.compile(r'^\s*(?:[-*]\s+|#+\s*)?(root_cause|command_output|fix|verification)\s*:\s*(.*)\s*$')
    for line in lines:
        m = section_pattern.match(line)
        if m:
            current = m.group(1)
            rest = m.group(2)
            sections[current] = rest.strip()
            continue
        if current is not None:
            if sections[current]:
                sections[current] += "\n" + line
            else:
                sections[current] = line
    for k in list(sections.keys()):
        sections[k] = sections[k].strip()
    return sections


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "failed_startup_captured": 0.0,
        "config_port_updated": 0.0,
        "config_host_unchanged_after_update": 0.0,
        "config_reliability_fields": 0.0,
        "server_startup_success": 0.0,
        "incident_report_root_cause": 0.0,
        "incident_report_command_output": 0.0,
        "incident_report_fix_section": 0.0,
        "incident_report_verification": 0.0,
    }

    prev_log_path = workspace / "logs" / "previous_run.log"
    failed_start_path = workspace / "out" / "failed_startup.txt"
    server_start_path = workspace / "out" / "server_startup.txt"
    config_path = workspace / "config" / "settings.json"
    incident_report_path = workspace / "out" / "incident_report.md"

    prev_log_text = _safe_read_text(prev_log_path)
    prev_lines = _split_maybe_escaped_lines(prev_log_text if prev_log_text is not None else "")
    expected_host_initial = "127.0.0.1"
    expected_port_initial = 8080
    root_cause_line = _find_address_in_use_line(prev_lines, host=expected_host_initial, port=expected_port_initial)

    failed_text = _safe_read_text(failed_start_path)
    failed_lines = _split_maybe_escaped_lines(failed_text if failed_text is not None else "")
    failed_error_line = _find_address_in_use_line(failed_lines, host=expected_host_initial, port=expected_port_initial)

    if failed_error_line is not None and failed_text is not None:
        scores["failed_startup_captured"] = 1.0

    cfg = _safe_load_json(config_path)
    if isinstance(cfg, dict):
        try:
            port_val = int(cfg.get("port", None))
        except Exception:
            port_val = None
        if port_val == 8081:
            scores["config_port_updated"] = 1.0
            # Only award host unchanged if the update to port occurred (prevents baseline credit)
            if cfg.get("host") == expected_host_initial:
                scores["config_host_unchanged_after_update"] = 1.0
        auto_restart_ok = (cfg.get("auto_restart") is True)
        max_restarts_ok = (cfg.get("max_restarts") == 2)
        if auto_restart_ok and max_restarts_ok:
            scores["config_reliability_fields"] = 1.0

    server_text = _safe_read_text(server_start_path)
    server_lines = _split_maybe_escaped_lines(server_text if server_text is not None else "")
    serving_line = _find_serving_line(server_lines)
    clean_exit_present = any("Setlist viewer exited cleanly." in ln for ln in server_lines) if server_lines else False
    serving_line_ok = False
    if serving_line:
        host_ok = expected_host_initial in serving_line
        port_ok = "8081" in serving_line
        serving_line_ok = host_ok and port_ok
    if serving_line_ok and clean_exit_present and server_text is not None:
        scores["server_startup_success"] = 1.0

    ir_text = _safe_read_text(incident_report_path)
    sections = _parse_incident_sections(ir_text if ir_text is not None else "")

    if root_cause_line and sections.get("root_cause"):
        if root_cause_line in sections["root_cause"]:
            scores["incident_report_root_cause"] = 1.0

    if failed_error_line and sections.get("command_output"):
        if failed_error_line in sections["command_output"]:
            scores["incident_report_command_output"] = 1.0

    fix_content = sections.get("fix", "")
    if fix_content:
        host_snip = re.search(r'"host"\s*:\s*"127\.0\.0\.1"', fix_content) is not None
        port_snip = re.search(r'"port"\s*:\s*8081\b', fix_content) is not None
        if host_snip and port_snip:
            scores["incident_report_fix_section"] = 1.0

    if serving_line and sections.get("verification"):
        if serving_line in sections["verification"]:
            scores["incident_report_verification"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()