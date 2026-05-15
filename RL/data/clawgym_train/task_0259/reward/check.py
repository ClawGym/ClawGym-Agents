import json
import sys
import os
import re
import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _extract_heredoc_log(script_text: str) -> Optional[str]:
    # Extract content between a line containing "cat <<'LOG'" and a line that is exactly "LOG"
    lines = _normalize_newlines(script_text).split("\n")
    start_idx = None
    for i, line in enumerate(lines):
        if "cat <<'LOG'" in line:
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    collected = []
    for j in range(start_idx, len(lines)):
        if lines[j].strip() == "LOG":
            break
        collected.append(lines[j])
    else:
        # Did not find closing LOG
        return None
    # Join with newlines, keep structure as in file
    return "\n".join(collected)


def _parse_services_yaml(yaml_text: str) -> Optional[List[Dict]]:
    # Minimal parser tailored to provided YAML structure
    # Expected structure:
    # services:
    #   - name: gateway
    #     port: 8080
    #     start_priority: 10
    #     ...
    try:
        lines = _normalize_newlines(yaml_text).split("\n")
        in_services = False
        services: List[Dict] = []
        current: Optional[Dict] = None
        for line in lines:
            stripped = line.strip()
            if not in_services:
                if stripped.startswith("services:"):
                    in_services = True
                continue
            # Skip empty lines or comments
            if not stripped or stripped.startswith("#"):
                continue
            # Detect new service entry
            m_name = re.match(r"^\s*-\s*name:\s*([^\s#]+)\s*$", line)
            if m_name:
                name_val = m_name.group(1)
                # Strip possible surrounding quotes
                if (name_val.startswith('"') and name_val.endswith('"')) or (name_val.startswith("'") and name_val.endswith("'")):
                    name_val = name_val[1:-1]
                current = {"name": name_val}
                services.append(current)
                continue
            if current is None:
                continue
            # Parse port
            m_port = re.match(r"^\s*port:\s*(\d+)\s*$", line)
            if m_port:
                current["port"] = int(m_port.group(1))
                continue
            # Parse start_priority
            m_pri = re.match(r"^\s*start_priority:\s*(\d+)\s*$", line)
            if m_pri:
                current["start_priority"] = int(m_pri.group(1))
                continue
        # Filter to only those with required keys
        cleaned = []
        for svc in services:
            if all(k in svc for k in ("name", "port", "start_priority")):
                cleaned.append(svc)
        if not cleaned:
            return None
        return cleaned
    except Exception:
        return None


def _parse_boot_log(log_text: str) -> Dict[str, Dict[str, int]]:
    # Parse lines like:
    # 2026-... [service] UP in 1120 ms
    # 2026-... [service] FAIL after 900 ms
    results: Dict[str, Dict[str, int]] = {}
    for line in _normalize_newlines(log_text).split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.search(r"\[(?P<service>[^\]]+)\]\s+(?P<status>UP|FAIL)\s+(?:in|after)\s+(?P<ms>\d+)\s+ms", line)
        if m:
            svc = m.group("service")
            status = m.group("status")
            ms = int(m.group("ms"))
            results[svc] = {"status": status, "ms": ms}
    return results


def _read_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "mock_boot_log_matches_expected": 0.0,
        "startup_csv_header_correct": 0.0,
        "startup_csv_up_rows_correct": 0.0,
        "startup_csv_sorted_and_ranked": 0.0,
        "failed_services_list_correct": 0.0,
        "port_conflicts_report_correct": 0.0,
        "start_script_executable": 0.0,
        "start_plan_log_correct": 0.0,
    }

    # Load inputs
    services_yaml_path = workspace / "input/config/services.yaml"
    services_yaml_text = _read_text(services_yaml_path)
    services_list = _parse_services_yaml(services_yaml_text) if services_yaml_text is not None else None
    services_by_name: Dict[str, Dict] = {}
    if services_list is not None:
        services_by_name = {s["name"]: s for s in services_list}

    mock_script_path = workspace / "input/scripts/mock_boot.sh"
    mock_script_text = _read_text(mock_script_path)
    expected_log_content = None
    if mock_script_text is not None:
        expected_log_content = _extract_heredoc_log(mock_script_text)

    # 1) Check mock_boot.log against expected heredoc content
    mock_boot_log_path = workspace / "logs" / "mock_boot.log"
    mock_boot_log_text = _read_text(mock_boot_log_path)
    if expected_log_content is not None and mock_boot_log_text is not None:
        exp_norm = _normalize_newlines(expected_log_content).rstrip("\n")
        act_norm = _normalize_newlines(mock_boot_log_text).rstrip("\n")
        if act_norm == exp_norm:
            scores["mock_boot_log_matches_expected"] = 1.0

    # Prepare parsed boot results from actual produced log (authoritative for downstream checks)
    boot_parsed: Dict[str, Dict[str, int]] = {}
    if mock_boot_log_text is not None:
        boot_parsed = _parse_boot_log(mock_boot_log_text)

    # 2) startup_times.csv checks
    startup_csv_path = workspace / "reports" / "startup_times.csv"
    csv_parsed = _read_csv(startup_csv_path)
    expected_header = ["service", "configured_port", "status", "startup_ms", "rank_slowest_first"]
    if csv_parsed is not None:
        header, rows = csv_parsed
        if header == expected_header:
            scores["startup_csv_header_correct"] = 1.0

        # Compute expected UP services intersecting with YAML
        if services_list is not None and boot_parsed:
            up_in_log = {name: info["ms"] for name, info in boot_parsed.items() if info.get("status") == "UP"}
            up_services = [name for name in up_in_log.keys() if name in services_by_name]
            # Build expected rows data
            expected_rows_map: Dict[str, Dict] = {}
            for name in up_services:
                expected_rows_map[name] = {
                    "service": name,
                    "configured_port": services_by_name[name]["port"],
                    "status": "UP",
                    "startup_ms": up_in_log[name],
                }
            # Validate rows content irrespective of order
            actual_rows_map: Dict[str, Dict] = {}
            valid_format = True
            seen_services: set = set()
            for r in rows:
                if len(r) != 5:
                    valid_format = False
                    break
                svc, port_str, status, ms_str, rank_str = r
                # basic type checks
                try:
                    port_val = int(port_str)
                    ms_val = int(ms_str)
                    int(rank_str)  # rank will be validated later
                except Exception:
                    valid_format = False
                    break
                if svc in seen_services:
                    valid_format = False
                    break
                seen_services.add(svc)
                actual_rows_map[svc] = {
                    "service": svc,
                    "configured_port": port_val,
                    "status": status,
                    "startup_ms": ms_val,
                    "rank": int(rank_str),
                }
            if valid_format:
                # Check that actual rows cover exactly expected UP services and match values
                if set(actual_rows_map.keys()) == set(expected_rows_map.keys()):
                    rows_match = True
                    for svc, exp in expected_rows_map.items():
                        act = actual_rows_map.get(svc)
                        if act is None:
                            rows_match = False
                            break
                        if not (
                            act["service"] == exp["service"]
                            and act["configured_port"] == exp["configured_port"]
                            and act["status"] == exp["status"]
                            and act["startup_ms"] == exp["startup_ms"]
                        ):
                            rows_match = False
                            break
                    if rows_match:
                        scores["startup_csv_up_rows_correct"] = 1.0

                # Check sorting by startup_ms desc and ranking 1..N in that order
                # Build expected order by ms desc
                exp_sorted = sorted(
                    expected_rows_map.values(), key=lambda d: d["startup_ms"], reverse=True
                )
                # Build actual order as in CSV file
                actual_sorted = []
                for r in rows:
                    svc = r[0]
                    actual_sorted.append(actual_rows_map[svc])
                # Validate order matches expected by service sequence
                order_ok = True
                if len(actual_sorted) != len(exp_sorted):
                    order_ok = False
                else:
                    for i in range(len(exp_sorted)):
                        if actual_sorted[i]["service"] != exp_sorted[i]["service"]:
                            order_ok = False
                            break
                # Validate rank
                rank_ok = True
                if order_ok:
                    for i, rowd in enumerate(actual_sorted):
                        if rowd["rank"] != i + 1:
                            rank_ok = False
                            break
                else:
                    rank_ok = False
                if order_ok and rank_ok:
                    scores["startup_csv_sorted_and_ranked"] = 1.0

    # 3) failed_services.txt checks
    failed_path = workspace / "reports" / "failed_services.txt"
    failed_text = _read_text(failed_path)
    if services_list is not None and boot_parsed and failed_text is not None:
        up_set = {name for name, info in boot_parsed.items() if info.get("status") == "UP"}
        # Services declared in YAML but not UP in log
        failed_services = [s["name"] for s in services_list if s["name"] not in up_set]
        expected_failed_lines = [f"{name}:{services_by_name[name]['port']}" for name in sorted(failed_services)]
        actual_lines = [ln.strip() for ln in _normalize_newlines(failed_text).split("\n") if ln.strip() != ""]
        if actual_lines == expected_failed_lines:
            scores["failed_services_list_correct"] = 1.0

    # 4) port_conflicts.txt checks
    conflicts_path = workspace / "reports" / "port_conflicts.txt"
    conflicts_text = _read_text(conflicts_path)
    if services_list is not None and conflicts_text is not None:
        port_map: Dict[int, List[str]] = {}
        for s in services_list:
            port_map.setdefault(s["port"], []).append(s["name"])
        expected_conflicts = {p: sorted(names) for p, names in port_map.items() if len(names) >= 2}
        # Parse actual
        actual_lines = [ln.strip() for ln in _normalize_newlines(conflicts_text).split("\n") if ln.strip() != ""]
        actual_conflicts: Dict[int, List[str]] = {}
        parsed_ok = True
        # Check numeric port ascending order
        prev_port = None
        for ln in actual_lines:
            if ": " not in ln:
                parsed_ok = False
                break
            port_str, names_csv = ln.split(": ", 1)
            try:
                port_val = int(port_str)
            except Exception:
                parsed_ok = False
                break
            names = [n.strip() for n in names_csv.split(",") if n.strip() != ""]
            if len(names) < 2:
                parsed_ok = False
                break
            actual_conflicts[port_val] = names
            if prev_port is not None and port_val < prev_port:
                parsed_ok = False
                break
            prev_port = port_val
        if parsed_ok:
            # Compare ports exactly
            if set(actual_conflicts.keys()) == set(expected_conflicts.keys()):
                # For each port, ensure same set of service names (order within line can be any)
                names_ok = True
                for p, exp_names in expected_conflicts.items():
                    if set(actual_conflicts.get(p, [])) != set(exp_names):
                        names_ok = False
                        break
                if names_ok:
                    scores["port_conflicts_report_correct"] = 1.0

    # 5) start_services.sh executable and start_plan.log correctness
    start_script_path = workspace / "workspace" / "bin" / "start_services.sh"  # incorrect; users should create under workspace/bin/start_services.sh
    # Correct path as per task:
    start_script_path = workspace / "bin" / "start_services.sh"
    if start_script_path.exists() and os.access(start_script_path, os.X_OK):
        scores["start_script_executable"] = 1.0

    start_plan_log_path = workspace / "logs" / "start_plan.log"
    start_plan_text = _read_text(start_plan_log_path)
    if services_list is not None and start_plan_text is not None:
        expected_lines = [f"START {s['name']} {s['port']}" for s in sorted(services_list, key=lambda d: d["start_priority"])]
        actual_lines = [ln for ln in _normalize_newlines(start_plan_text).split("\n") if ln != ""]
        if actual_lines == expected_lines:
            scores["start_plan_log_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()