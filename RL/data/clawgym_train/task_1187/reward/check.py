import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        datetime.fromisoformat(t)
        return True
    except Exception:
        # Fallback pattern for basic ISO timestamps without timezone
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", s))


def _parse_config_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser tailored for the provided config.yaml structure.
    Supports:
      - top-level scalars: min_free_gb (float), max_python_procs (int)
      - list of scalars under crypto_tools
      - list of mappings under sensitive_files with keys path and require_no_world_writable (bool)
    Returns dict or None on failure.
    """
    content = _safe_read_text(path)
    if content is None:
        return None
    lines = content.splitlines()
    cfg: Dict[str, Any] = {}
    n = len(lines)
    try:
        # Parse simple scalars
        for j in range(n):
            m1 = re.match(r"^\s*min_free_gb:\s*([0-9]+(?:\.[0-9]+)?)\s*$", lines[j])
            if m1:
                cfg["min_free_gb"] = float(m1.group(1))
            m2 = re.match(r"^\s*max_python_procs:\s*([0-9]+)\s*$", lines[j])
            if m2:
                cfg["max_python_procs"] = int(m2.group(1))
        # Parse crypto_tools
        crypto_tools: List[str] = []
        for j in range(n):
            if re.match(r"^\s*crypto_tools:\s*$", lines[j]):
                k = j + 1
                while k < n and (re.match(r"^\s*-\s+.+", lines[k]) or re.match(r"^\s*$", lines[k])):
                    m = re.match(r"^\s*-\s+(.+)\s*$", lines[k])
                    if m:
                        crypto_tools.append(m.group(1).strip())
                    k += 1
                break
        if crypto_tools:
            cfg["crypto_tools"] = crypto_tools
        # Parse sensitive_files
        sensitive_files: List[Dict[str, Any]] = []
        for j in range(n):
            if re.match(r"^\s*sensitive_files:\s*$", lines[j]):
                k = j + 1
                current: Dict[str, Any] = {}
                while k < n and (re.match(r"^\s*-\s+.*", lines[k]) or re.match(r"^\s+\S", lines[k]) or re.match(r"^\s*$", lines[k])):
                    line = lines[k]
                    # Start of new item
                    if re.match(r"^\s*-\s+.*", line):
                        if current:
                            sensitive_files.append(current)
                            current = {}
                    else:
                        pm = re.match(r"^\s*path:\s*(.+?)\s*$", line)
                        rm = re.match(r"^\s*require_no_world_writable:\s*(true|false)\s*$", line, re.IGNORECASE)
                        if pm:
                            current["path"] = pm.group(1).strip()
                        if rm:
                            current["require_no_world_writable"] = rm.group(1).strip().lower() == "true"
                    k += 1
                if current:
                    sensitive_files.append(current)
                break
        if sensitive_files:
            cfg["sensitive_files"] = sensitive_files
        # Validate presence of required keys
        required_keys = ["min_free_gb", "max_python_procs", "crypto_tools", "sensitive_files"]
        for rk in required_keys:
            if rk not in cfg:
                return None
        return cfg
    except Exception:
        return None


def _find_check_by_name(checks: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for c in checks:
        if isinstance(c, dict) and c.get("name") == name:
            return c
    return None


def _deep_contains_string(obj: Any, target: str) -> bool:
    try:
        if isinstance(obj, str):
            return obj == target
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if _deep_contains_string(k, target) or _deep_contains_string(v, target):
                    return True
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                if _deep_contains_string(item, target):
                    return True
        else:
            return False
    except Exception:
        return False
    return False


def _get_summary_counts(obj: Dict[str, Any]) -> Optional[Tuple[int, int, int]]:
    s = obj.get("summary")
    if not isinstance(s, dict):
        return None
    try:
        p = int(s.get("pass"))
        f = int(s.get("fail"))
        e = int(s.get("error"))
        return (p, f, e)
    except Exception:
        return None


def _validate_check_item_structure(item: Dict[str, Any]) -> bool:
    # Required keys: name, status, commands (list of strings), stdout string, stderr string, metrics dict, policy dict
    if not isinstance(item, dict):
        return False
    if item.get("name") not in {"disk_space", "os_info", "crypto_tools", "python_processes", "file_permissions"}:
        return False
    if item.get("status") not in {"pass", "fail", "error"}:
        return False
    cmds = item.get("commands")
    if not isinstance(cmds, list) or len(cmds) == 0 or not all(isinstance(x, str) for x in cmds):
        return False
    if not isinstance(item.get("stdout"), str):
        return False
    if not isinstance(item.get("stderr"), str):
        return False
    if not isinstance(item.get("metrics"), dict):
        return False
    if not isinstance(item.get("policy"), dict):
        return False
    return True


def _extract_section(text: str, section_name: str) -> Optional[str]:
    """
    Extracts a section by heading name (case-insensitive).
    Accepts headings like:
      - "Section Name"
      - "Section Name:"
      - "# Section Name"
      - "## Section Name"
    Returns the content from the line after the heading until the next heading or end of file.
    """
    lines = text.splitlines()
    idx_start = None
    normalized = section_name.strip().lower().rstrip(":")
    for i, line in enumerate(lines):
        l = line.strip().lower().rstrip(":")
        if l == normalized or l == f"# {normalized}" or l == f"## {normalized}" or l == f"### {normalized}":
            idx_start = i + 1
            break
    if idx_start is None:
        for i, line in enumerate(lines):
            l = line.strip().lower()
            if normalized in l and (l.startswith("#") or l.endswith(":") or l == normalized):
                idx_start = i + 1
                break
    if idx_start is None:
        return None
    end = len(lines)
    known_sections = {"executive summary", "detailed results", "next steps"}
    for j in range(idx_start, len(lines)):
        l = lines[j].strip().lower().rstrip(":")
        if l.startswith("#") or l in known_sections:
            end = j
            break
    section_text = "\n".join(lines[idx_start:end]).strip()
    return section_text


def _count_bullet_lines(text: str) -> int:
    if not text:
        return 0
    count = 0
    for line in text.splitlines():
        if re.match(r"^\s*[-*]\s+", line):
            count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    # Initialize scores in a stable alphabetical order to match CLI and direct-call expectations
    scores: Dict[str, float] = {
        "cross_report_json_counts_consistency": 0.0,
        "disk_space_metrics_include_available_gb": 0.0,
        "executive_summary_mentions_counts_and_constraints": 0.0,
        "json_check_items_well_formed": 0.0,
        "json_checks_include_required_names": 0.0,
        "json_file_exists": 0.0,
        "json_parseable": 0.0,
        "json_top_level_fields": 0.0,
        "json_validation_log_present_and_consistent": 0.0,
        "next_steps_items_if_failures": 0.0,
        "policy_thresholds_match_config": 0.0,
        "python_processes_metrics_include_python_count": 0.0,
        "report_exists_and_sections": 0.0,
        "summary_counts_consistent": 0.0,
    }

    output_json_path = workspace / "output" / "system_risk_checks.json"
    report_md_path = workspace / "output" / "system_risk_checks_report.md"
    json_validation_log_path = workspace / "output" / "json_validation.log"
    config_yaml_path = workspace / "input" / "config.yaml"

    cfg = _parse_config_yaml(config_yaml_path)

    # JSON existence and parseability
    if output_json_path.exists():
        scores["json_file_exists"] = 1.0
    data = _safe_load_json(output_json_path)
    if data is not None:
        scores["json_parseable"] = 1.0

    # JSON top-level fields
    if isinstance(data, dict):
        try:
            ts = data.get("timestamp")
            host = data.get("host")
            osinfo = data.get("os")
            checks = data.get("checks")
            summary = data.get("summary")
            if (
                isinstance(ts, str) and _is_iso8601(ts)
                and isinstance(host, str) and len(host.strip()) > 0
                and isinstance(osinfo, dict)
                and isinstance(osinfo.get("kernel"), str) and osinfo.get("kernel")
                and isinstance(osinfo.get("version"), str) and osinfo.get("version")
                and isinstance(osinfo.get("machine"), str) and osinfo.get("machine")
                and isinstance(checks, list)
                and isinstance(summary, dict)
                and isinstance(summary.get("pass"), int)
                and isinstance(summary.get("fail"), int)
                and isinstance(summary.get("error"), int)
            ):
                scores["json_top_level_fields"] = 1.0
        except Exception:
            pass

    # JSON checks include required names and structure
    required_names = {"disk_space", "os_info", "crypto_tools", "python_processes", "file_permissions"}
    if isinstance(data, dict) and isinstance(data.get("checks"), list):
        names_present = set()
        structure_ok = True
        for item in data["checks"]:
            if isinstance(item, dict) and "name" in item:
                names_present.add(item.get("name"))
            if not _validate_check_item_structure(item):
                structure_ok = False
        if required_names.issubset(names_present):
            scores["json_checks_include_required_names"] = 1.0
        if structure_ok:
            scores["json_check_items_well_formed"] = 1.0

    # Policy thresholds match config
    if cfg is not None and isinstance(data, dict) and isinstance(data.get("checks"), list):
        disk = _find_check_by_name(data["checks"], "disk_space")
        pyprocs = _find_check_by_name(data["checks"], "python_processes")
        crypto = _find_check_by_name(data["checks"], "crypto_tools")
        fperm = _find_check_by_name(data["checks"], "file_permissions")

        ok = True
        # Disk
        if isinstance(disk, dict) and isinstance(disk.get("policy"), dict):
            pol = disk["policy"]
            min_free = pol.get("min_free_gb")
            if not isinstance(min_free, (int, float)) or abs(float(min_free) - float(cfg["min_free_gb"])) > 1e-6:
                ok = False
        else:
            ok = False
        # Python processes
        if isinstance(pyprocs, dict) and isinstance(pyprocs.get("policy"), dict):
            pol = pyprocs["policy"]
            maxp = pol.get("max_python_procs")
            if not isinstance(maxp, int) or int(maxp) != int(cfg["max_python_procs"]):
                ok = False
        else:
            ok = False
        # Crypto tools
        if isinstance(crypto, dict) and isinstance(crypto.get("policy"), dict):
            pol = crypto["policy"]
            ct = pol.get("crypto_tools")
            if isinstance(ct, list) and all(isinstance(x, str) for x in ct):
                if not set(cfg["crypto_tools"]).issubset(set(ct)):
                    ok = False
            else:
                ok = False
        else:
            ok = False
        # File permissions
        if isinstance(fperm, dict) and isinstance(fperm.get("policy"), dict):
            pol = fperm["policy"]

            def _scan_for_req(obj: Any) -> bool:
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(k, str) and k == "require_no_world_writable" and isinstance(v, bool) and v is True:
                            return True
                        if _scan_for_req(v):
                            return True
                elif isinstance(obj, list):
                    for x in obj:
                        if _scan_for_req(x):
                            return True
                return False

            req_nww = _scan_for_req(pol)
            has_path = False
            target_path = None
            try:
                if isinstance(cfg.get("sensitive_files"), list) and cfg["sensitive_files"]:
                    target_path = cfg["sensitive_files"][0].get("path")
            except Exception:
                target_path = None
            if target_path:
                has_path = _deep_contains_string(pol, target_path)
            if not (req_nww and has_path):
                ok = False
        else:
            ok = False

        if ok:
            scores["policy_thresholds_match_config"] = 1.0

    # Metrics presence checks
    if isinstance(data, dict) and isinstance(data.get("checks"), list):
        disk = _find_check_by_name(data["checks"], "disk_space")
        if isinstance(disk, dict) and isinstance(disk.get("metrics"), dict):
            av = disk["metrics"].get("available_gb")
            if isinstance(av, (int, float)):
                scores["disk_space_metrics_include_available_gb"] = 1.0
        pyprocs = _find_check_by_name(data["checks"], "python_processes")
        if isinstance(pyprocs, dict) and isinstance(pyprocs.get("metrics"), dict):
            pc = pyprocs["metrics"].get("python_count")
            if isinstance(pc, int):
                scores["python_processes_metrics_include_python_count"] = 1.0

    # Summary counts consistent with checks
    if isinstance(data, dict) and isinstance(data.get("checks"), list):
        counts = {"pass": 0, "fail": 0, "error": 0}
        ok_statuses = {"pass", "fail", "error"}
        for item in data["checks"]:
            st = item.get("status")
            if st in ok_statuses:
                counts[st] += 1
        s_tuple = _get_summary_counts(data)
        if s_tuple is not None:
            sp, sf, se = s_tuple
            if sp == counts["pass"] and sf == counts["fail"] and se == counts["error"]:
                scores["summary_counts_consistent"] = 1.0

    # Report exists and sections
    report_text = _safe_read_text(report_md_path)
    if report_text is not None:
        lines = [ln for ln in report_text.splitlines() if ln.strip()]
        has_title = len(lines) > 0
        has_date = bool(re.search(r"\b20\d{2}\b", report_text))
        has_exec = _extract_section(report_text, "Executive Summary") is not None
        has_detail = _extract_section(report_text, "Detailed Results") is not None
        has_next = _extract_section(report_text, "Next Steps") is not None
        if has_title and has_date and has_exec and has_detail and has_next:
            scores["report_exists_and_sections"] = 1.0

    # Executive summary mentions counts and constraints
    if report_text is not None:
        exec_sec = _extract_section(report_text, "Executive Summary")
        if exec_sec:
            has_counts_terms = (
                re.search(r"\bpass\b", exec_sec, flags=re.IGNORECASE) is not None
                and re.search(r"\bfail\b", exec_sec, flags=re.IGNORECASE) is not None
                and re.search(r"\berror\b", exec_sec, flags=re.IGNORECASE) is not None
            )
            has_any_digits = re.search(r"\d+", exec_sec) is not None
            mentions_disk = re.search(r"\bdisk\b", exec_sec, flags=re.IGNORECASE) is not None
            mentions_python = re.search(r"\bpython\b", exec_sec, flags=re.IGNORECASE) is not None
            if has_counts_terms and has_any_digits and mentions_disk and mentions_python:
                scores["executive_summary_mentions_counts_and_constraints"] = 1.0

    # Next Steps action items if failures occurred
    if isinstance(data, dict):
        s_tuple2 = _get_summary_counts(data)
    else:
        s_tuple2 = None
    if report_text is not None and s_tuple2 is not None:
        _, fail_count, _ = s_tuple2
        next_sec = _extract_section(report_text, "Next Steps")
        if fail_count > 0:
            if next_sec:
                bullets = _count_bullet_lines(next_sec)
                if 2 <= bullets <= 4:
                    scores["next_steps_items_if_failures"] = 1.0
        else:
            scores["next_steps_items_if_failures"] = 1.0

    # JSON validation log present and consistent
    log_text = _safe_read_text(json_validation_log_path)
    if log_text is not None:
        lines = [ln.strip() for ln in log_text.splitlines() if ln.strip()]
        last_line = lines[-1] if lines else ""
        contains_cmd = "system_risk_checks.json" in log_text
        mcode = re.search(r"(?i)exit\s*code[: ]+(-?\d+)", log_text)
        code = None
        if mcode:
            try:
                code = int(mcode.group(1))
            except Exception:
                code = None
        has_ok = re.search(r"\bOK\b", last_line) is not None
        has_failed = re.search(r"\bFAILED\b", last_line) is not None
        consistent = False
        if contains_cmd and code is not None:
            if has_ok and code == 0:
                consistent = True
            elif has_failed and code != 0:
                consistent = True
        if consistent:
            scores["json_validation_log_present_and_consistent"] = 1.0

    # Cross-check JSON summary counts appear in Executive Summary
    if isinstance(data, dict) and report_text is not None:
        s_tuple3 = _get_summary_counts(data)
        exec_sec2 = _extract_section(report_text, "Executive Summary")
        if s_tuple3 is not None and exec_sec2:
            sp, sf, se = s_tuple3
            ok_nums = (str(sp) in exec_sec2 and str(sf) in exec_sec2 and str(se) in exec_sec2)
            if ok_nums:
                scores["cross_report_json_counts_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()