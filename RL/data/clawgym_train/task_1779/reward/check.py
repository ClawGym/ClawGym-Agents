import json
import csv
import sys
import re
import shlex
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_csv_with_header(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
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


def _list_files(root: Path, pattern: str) -> List[Path]:
    # pattern like "*.list"
    return sorted([p for p in root.glob(pattern) if p.is_file()])


def _list_files_recursive(root: Path, subpath: str, pattern: str) -> List[Path]:
    base = root / subpath
    if not base.exists():
        return []
    return sorted([p for p in base.rglob(pattern) if p.is_file()])


def _parse_apt_sources(list_files: List[Path]) -> List[Dict]:
    repos = []
    for lf in sorted(list_files):
        content = _read_text(lf)
        if content is None:
            continue
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not (line.startswith("deb ") or line.startswith("deb-src ")):
                continue
            tokens = line.split()
            if len(tokens) < 3:
                continue
            repo_type = tokens[0]
            i = 1
            if i < len(tokens) and tokens[i].startswith("["):
                # Consume option tokens until ']'
                while i < len(tokens) and not tokens[i].endswith("]"):
                    i += 1
                if i < len(tokens) and tokens[i].endswith("]"):
                    i += 1
            if i + 1 >= len(tokens):
                continue
            uri = tokens[i]
            suite = tokens[i + 1]
            components = tokens[i + 2:] if (i + 2) < len(tokens) else []
            repos.append({
                "type": repo_type,
                "uri": uri,
                "suite": suite,
                "components": components
            })
    return repos


def _parse_apt_periodic_settings(conf_files: List[Path]) -> Dict[str, Optional[object]]:
    keys = ["Update-Package-Lists", "Download-Upgradeable-Packages", "Unattended-Upgrade"]
    result: Dict[str, Optional[object]] = {k: None for k in keys}
    # Deterministic order: sort by path name
    for cf in sorted(conf_files):
        text = _read_text(cf)
        if text is None:
            continue
        for line in text.splitlines():
            # Remove inline comments after // or # if present
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue
            m = re.search(r'APT::Periodic::(Update-Package-Lists|Download-Upgradeable-Packages|Unattended-Upgrade)\s+([^;]+);', stripped)
            if m:
                key = m.group(1)
                val_raw = m.group(2).strip()
                # Remove surrounding quotes if present
                if (val_raw.startswith('"') and val_raw.endswith('"')) or (val_raw.startswith("'") and val_raw.endswith("'")):
                    val = val_raw[1:-1]
                else:
                    # Try to parse numeric if unquoted
                    if re.fullmatch(r"-?\d+", val_raw):
                        try:
                            val = int(val_raw)
                        except Exception:
                            val = val_raw
                    else:
                        val = val_raw
                result[key] = val
    return result


def _parse_systemd_services(service_files: List[Path]) -> List[Dict]:
    telemetry_services: List[Dict] = []
    for sf in sorted(service_files):
        text = _read_text(sf)
        if text is None:
            continue
        current_section = None
        unit_desc = None
        service_type = None
        exec_start = None
        env_lines: List[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                key = k.strip()
                value = v.strip()
                if current_section == "Unit" and key.lower() == "description":
                    unit_desc = value
                if current_section == "Service":
                    if key.lower() == "type":
                        service_type = value
                    elif key.lower() == "execstart":
                        exec_start = value
                    elif key.lower() == "environment":
                        env_lines.append(value)
        # Determine if telemetry related: description or execstart contains "telemetry"
        telemetry_flag = False
        if unit_desc and ("telemetry" in unit_desc.lower()):
            telemetry_flag = True
        if exec_start and ("telemetry" in exec_start.lower()):
            telemetry_flag = True
        if telemetry_flag:
            telemetry_endpoint = None
            # Parse environment assignments
            for env_line in env_lines:
                # env_line may contain multiple assignments, possibly quoted
                try:
                    tokens = shlex.split(env_line)
                except Exception:
                    tokens = env_line.split()
                for tok in tokens:
                    if "=" in tok:
                        ek, ev = tok.split("=", 1)
                        if ek == "TELEMETRY_ENDPOINT":
                            telemetry_endpoint = ev
            telemetry_services.append({
                "unit": sf.name,
                "type": service_type if service_type is not None else None,
                "exec_start": exec_start if exec_start is not None else None,
                "telemetry_endpoint": telemetry_endpoint
            })
    return telemetry_services


def _parse_telemetry_conf(conf_path: Path) -> Dict[str, Optional[object]]:
    result = {"enabled": None, "endpoint": None}
    text = _read_text(conf_path)
    if text is None:
        return result
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip().lower()
        val_raw = v.strip()
        # Remove trailing comments at end of line starting with #
        if "#" in val_raw:
            # Only if comment starts after some space
            hash_index = val_raw.find("#")
            val_raw = val_raw[:hash_index].strip()
        # Strip trailing semicolons if present (not expected here)
        if val_raw.endswith(";"):
            val_raw = val_raw[:-1].strip()
        # Remove surrounding quotes
        if (val_raw.startswith('"') and val_raw.endswith('"')) or (val_raw.startswith("'") and val_raw.endswith("'")):
            val_clean = val_raw[1:-1]
        else:
            val_clean = val_raw
        if key == "enabled":
            lower = val_clean.strip().lower()
            if lower in ("true", "yes", "1"):
                result["enabled"] = True
            elif lower in ("false", "no", "0"):
                result["enabled"] = False
            else:
                # malformed boolean
                result["enabled"] = None
        elif key == "endpoint":
            result["endpoint"] = val_clean
    return result


def _compute_expected(workspace: Path) -> Dict[str, object]:
    # Determine inputs
    apt_dir = workspace / "input" / "apt"
    apt_list_files = _list_files(apt_dir, "*.list")
    apt_conf_dir = apt_dir / "apt.conf.d"
    apt_conf_files = []
    if apt_conf_dir.exists():
        apt_conf_files = sorted([p for p in apt_conf_dir.iterdir() if p.is_file()])
    systemd_service_files = _list_files(workspace / "input" / "systemd" / "system", "*.service")
    telemetry_conf = workspace / "input" / "telemetry" / "telemetry.conf"

    # Expected repos
    repos = _parse_apt_sources(apt_list_files)
    # Expected security flag
    security_present = any("security" in (r.get("suite", "").lower()) for r in repos)
    # Expected periodic settings
    periodic = _parse_apt_periodic_settings(apt_conf_files)
    # Expected telemetry services
    telemetry_services = _parse_systemd_services(systemd_service_files)
    # Expected telemetry config
    telemetry_cfg = _parse_telemetry_conf(telemetry_conf)

    # Required discovered files set (must be included by user)
    required_files = []
    for p in apt_list_files:
        required_files.append(p)
    for p in apt_conf_files:
        required_files.append(p)
    for p in systemd_service_files:
        required_files.append(p)
    if telemetry_conf.exists() and telemetry_conf.is_file():
        required_files.append(telemetry_conf)
    required_files_rel = sorted([p.relative_to(workspace).as_posix() for p in required_files])

    return {
        "repos": repos,
        "security_repo_present": security_present,
        "periodic_settings": periodic,
        "telemetry_services": telemetry_services,
        "telemetry_config": telemetry_cfg,
        "required_discovered_files": required_files_rel,
    }


def _load_discovered_files(path: Path, workspace: Path) -> Optional[List[str]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    # Normalize to posix-like
    return lines


def _validate_discovered_files(lines: List[str], workspace: Path) -> bool:
    # All must be relative and under input/, and exist
    for ln in lines:
        p = Path(ln)
        if p.is_absolute():
            return False
        full = (workspace / p).resolve()
        # Must be under workspace/input
        try:
            full.relative_to(workspace)
        except Exception:
            return False
        # Must start with input/
        try:
            rel = full.relative_to(workspace).as_posix()
        except Exception:
            return False
        if not rel.startswith("input/"):
            return False
        if not full.exists() or not full.is_file():
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "discovered_files_exists": 0.0,
        "discovered_files_paths_valid": 0.0,
        "discovered_files_includes_required": 0.0,
        "repo_list_exists": 0.0,
        "repo_list_csv_correct": 0.0,
        "system_policy_report_exists": 0.0,
        "system_policy_report_correct": 0.0,
        "csv_json_repos_consistent": 0.0,
    }

    expected = _compute_expected(workspace)

    # Check discovered_files.txt
    discovered_path = workspace / "output" / "discovered_files.txt"
    discovered_lines = _load_discovered_files(discovered_path, workspace)
    if discovered_lines is not None:
        scores["discovered_files_exists"] = 1.0
        if _validate_discovered_files(discovered_lines, workspace):
            scores["discovered_files_paths_valid"] = 1.0
        # Coverage of required files
        required = set(expected.get("required_discovered_files", []))
        listed = set(discovered_lines)
        if required:
            coverage = len(required & listed) / len(required)
            scores["discovered_files_includes_required"] = float(coverage)
        else:
            # If no required files (no inputs), consider as fully covered
            scores["discovered_files_includes_required"] = 1.0
    else:
        scores["discovered_files_exists"] = 0.0
        scores["discovered_files_paths_valid"] = 0.0
        scores["discovered_files_includes_required"] = 0.0

    # Build expected CSV rows
    expected_repos: List[Dict] = expected["repos"]  # each has type, uri, suite, components(list)
    expected_csv_rows = []
    for r in expected_repos:
        components_str = " ".join(r.get("components", []))
        expected_csv_rows.append([r.get("type", ""), r.get("uri", ""), r.get("suite", ""), components_str])

    # Check repo_list.csv
    repo_csv_path = workspace / "output" / "repo_list.csv"
    csv_parsed = _parse_csv_with_header(repo_csv_path)
    if csv_parsed is not None:
        scores["repo_list_exists"] = 1.0
        header, data_rows = csv_parsed
        header_ok = header == ["type", "uri", "suite", "components"]
        rows_ok = False
        if header_ok:
            # Compare rows exactly in order
            if len(data_rows) == len(expected_csv_rows):
                rows_ok = all(
                    [list(map(str, row)) == list(map(str, exp)) for row, exp in zip(data_rows, expected_csv_rows)]
                )
        if header_ok and rows_ok:
            scores["repo_list_csv_correct"] = 1.0
        else:
            scores["repo_list_csv_correct"] = 0.0
    else:
        scores["repo_list_exists"] = 0.0
        scores["repo_list_csv_correct"] = 0.0

    # Check system_policy_report.json
    report_path = workspace / "output" / "system_policy_report.json"
    report = _load_json(report_path)
    if report is not None and isinstance(report, dict):
        scores["system_policy_report_exists"] = 1.0
        correct = True

        # repos check
        exp_repos_objs = [
            {"type": r["type"], "uri": r["uri"], "suite": r["suite"], "components": r["components"]}
            for r in expected_repos
        ]
        rep_repos = report.get("repos")
        if not isinstance(rep_repos, list):
            correct = False
        else:
            # must match exactly in length and order
            if len(rep_repos) != len(exp_repos_objs):
                correct = False
            else:
                for a, b in zip(rep_repos, exp_repos_objs):
                    # Ensure components is list of strings
                    a_comp = a.get("components")
                    if not isinstance(a_comp, list) or any(not isinstance(x, str) for x in a_comp):
                        correct = False
                        break
                    if a.get("type") != b.get("type") or a.get("uri") != b.get("uri") or a.get("suite") != b.get("suite") or a_comp != b.get("components"):
                        correct = False
                        break

        # security_repo_present check
        if report.get("security_repo_present") != expected.get("security_repo_present"):
            correct = False

        # periodic_settings check
        rep_periodic = report.get("periodic_settings")
        if not isinstance(rep_periodic, dict):
            correct = False
        else:
            for k, v in expected.get("periodic_settings", {}).items():
                if k not in rep_periodic:
                    correct = False
                    break
                # Strict equality
                if rep_periodic.get(k) != v:
                    correct = False
                    break

        # telemetry_services check
        exp_services = expected.get("telemetry_services", [])
        rep_services = report.get("telemetry_services")
        if not isinstance(rep_services, list):
            correct = False
        else:
            # Expect exact list equal in length and content (order matters)
            if len(rep_services) != len(exp_services):
                correct = False
            else:
                for rs, es in zip(rep_services, exp_services):
                    if not isinstance(rs, dict):
                        correct = False
                        break
                    # Required keys
                    for k in ["unit", "type", "exec_start", "telemetry_endpoint"]:
                        if k not in rs:
                            correct = False
                            break
                    if not correct:
                        break
                    # Compare equality
                    if rs.get("unit") != es.get("unit"):
                        correct = False
                        break
                    if rs.get("type") != es.get("type"):
                        correct = False
                        break
                    if rs.get("exec_start") != es.get("exec_start"):
                        correct = False
                        break
                    if rs.get("telemetry_endpoint") != es.get("telemetry_endpoint"):
                        correct = False
                        break

        # telemetry_config check
        rep_tcfg = report.get("telemetry_config")
        exp_tcfg = expected.get("telemetry_config", {})
        if not isinstance(rep_tcfg, dict):
            correct = False
        else:
            # Must have enabled and endpoint keys
            if "enabled" not in rep_tcfg or "endpoint" not in rep_tcfg:
                correct = False
            else:
                if rep_tcfg.get("enabled") != exp_tcfg.get("enabled"):
                    correct = False
                if rep_tcfg.get("endpoint") != exp_tcfg.get("endpoint"):
                    correct = False

        scores["system_policy_report_correct"] = 1.0 if correct else 0.0
    else:
        scores["system_policy_report_exists"] = 0.0
        scores["system_policy_report_correct"] = 0.0

    # Cross-file consistency: CSV vs JSON repos
    csv_ok = scores["repo_list_csv_correct"] == 1.0
    json_ok = scores["system_policy_report_correct"] == 1.0
    if csv_ok and json_ok and report is not None:
        csv_header, csv_rows = _parse_csv_with_header(repo_csv_path)  # type: ignore
        # Build normalized list from CSV
        csv_repos = []
        if csv_header == ["type", "uri", "suite", "components"]:
            for row in csv_rows:
                if len(row) != 4:
                    csv_repos = []
                    break
                csv_repos.append(tuple(row))
        # Build from JSON
        json_repos = []
        rep_repos = report.get("repos")
        if isinstance(rep_repos, list):
            for r in rep_repos:
                if not isinstance(r, dict):
                    json_repos = []
                    break
                comps = r.get("components", [])
                if not isinstance(comps, list):
                    json_repos = []
                    break
                comps_str = " ".join(comps)
                json_repos.append((str(r.get("type")), str(r.get("uri")), str(r.get("suite")), comps_str))
        if csv_repos and json_repos and csv_repos == json_repos:
            scores["csv_json_repos_consistent"] = 1.0
        else:
            scores["csv_json_repos_consistent"] = 0.0
    else:
        scores["csv_json_repos_consistent"] = 0.0

    # Ensure all values are floats
    for k, v in list(scores.items()):
        try:
            scores[k] = float(v)
        except Exception:
            scores[k] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()