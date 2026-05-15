import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _get(d: Dict[str, Any], path: List[str], default: Any = None) -> Any:
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def _parse_scalar(token: str) -> Any:
    t = token.strip()
    if t.startswith('"') and t.endswith('"') and len(t) >= 2:
        return t[1:-1]
    if t.lower() == "true":
        return True
    if t.lower() == "false":
        return False
    if re.fullmatch(r"-?\d+", t):
        try:
            return int(t)
        except Exception:
            pass
    if re.fullmatch(r"-?\d+\.\d+", t):
        try:
            return float(t)
        except Exception:
            pass
    return t if t != "" else None


def _parse_recording_requirements_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    i = 0
    out: Dict[str, Any] = {}
    n = len(lines)

    def is_top_level(line: str) -> bool:
        return line.strip() != "" and not line.startswith(" ")

    while i < n:
        line = lines[i].rstrip()
        if line.strip() == "" or line.strip().startswith("#"):
            i += 1
            continue
        if is_top_level(line):
            stripped = line.strip()
            if stripped.startswith("project:"):
                parts = stripped.split(":", 1)
                val = parts[1].strip() if len(parts) > 1 else ""
                out["project"] = _parse_scalar(val)
                i += 1
                continue
            if stripped.startswith("notes:"):
                parts = stripped.split(":", 1)
                val = parts[1].strip() if len(parts) > 1 else ""
                out["notes"] = _parse_scalar(val)
                i += 1
                continue
            if stripped.startswith("requirements:"):
                req: Dict[str, Any] = {}
                i += 1
                while i < n:
                    l = lines[i].rstrip()
                    if l.strip() == "" or l.strip().startswith("#"):
                        i += 1
                        continue
                    if not l.startswith("  "):
                        break
                    s = l.strip()
                    if s.startswith("preferred_os:"):
                        arr: List[Any] = []
                        i += 1
                        while i < n:
                            li = lines[i].rstrip()
                            if li.strip() == "" or li.strip().startswith("#"):
                                i += 1
                                continue
                            if li.startswith("    - "):
                                item = li.strip()[2:].strip()
                                arr.append(_parse_scalar(item))
                                i += 1
                                continue
                            else:
                                break
                        req["preferred_os"] = arr
                        continue
                    else:
                        if ":" in s:
                            k, v = s.split(":", 1)
                            key = k.strip()
                            val = v.strip()
                            req[key] = _parse_scalar(val)
                            i += 1
                            continue
                        else:
                            break
                out["requirements"] = req
                continue
            if stripped.startswith("optional:"):
                opt: Dict[str, Any] = {}
                i += 1
                while i < n:
                    l = lines[i].rstrip()
                    if l.strip() == "" or l.strip().startswith("#"):
                        i += 1
                        continue
                    if not l.startswith("  "):
                        break
                    s = l.strip()
                    if ":" in s:
                        k, v = s.split(":", 1)
                        key = k.strip()
                        val = v.strip()
                        opt[key] = _parse_scalar(val)
                        i += 1
                        continue
                    else:
                        break
                out["optional"] = opt
                continue
            i += 1
        else:
            i += 1
    if not isinstance(out.get("project"), str):
        return None
    if not isinstance(out.get("requirements"), dict):
        return None
    if "preferred_os" in out.get("requirements", {}):
        if not isinstance(out["requirements"]["preferred_os"], list):
            return None
    if "optional" in out and not isinstance(out["optional"], dict):
        return None
    if "notes" in out and not isinstance(out["notes"], str):
        return None
    return out


def _normalize_os_name(name: Optional[str]) -> Optional[str]:
    if not isinstance(name, str):
        return None
    return name.strip().lower()


def _status_expected_from_yaml_and_measured(yaml_dict: Dict[str, Any], json_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    try:
        reqs = yaml_dict["requirements"]
        eval_expected: Dict[str, str] = {}

        threshold_disk = reqs.get("min_free_disk_gb")
        measured_free_disk = _get(json_data, ["disk", "free_gb"], None)
        if _is_number(measured_free_disk) and _is_number(threshold_disk):
            eval_expected["min_free_disk_gb"] = "pass" if float(measured_free_disk) >= float(threshold_disk) else "fail"
        else:
            eval_expected["min_free_disk_gb"] = "unknown"

        threshold_ram = reqs.get("min_total_ram_gb")
        measured_ram = _get(json_data, ["memory", "total_gb"], None)
        if _is_number(measured_ram) and _is_number(threshold_ram):
            eval_expected["min_total_ram_gb"] = "pass" if float(measured_ram) >= float(threshold_ram) else "fail"
        else:
            eval_expected["min_total_ram_gb"] = "unknown"

        pref_list = reqs.get("preferred_os")
        measured_os = _normalize_os_name(_get(json_data, ["os", "name"], None))
        if isinstance(pref_list, list) and measured_os is not None:
            pref_norm = [str(x).strip().lower() for x in pref_list]
            eval_expected["preferred_os"] = "pass" if measured_os in pref_norm else "fail"
        else:
            eval_expected["preferred_os"] = "unknown"

        threshold_cpu = reqs.get("max_background_cpu_percent")
        measured_cpu = _get(json_data, ["measurements", "background_cpu_percent"], None)
        if _is_number(measured_cpu) and _is_number(threshold_cpu):
            eval_expected["max_background_cpu_percent"] = "pass" if float(measured_cpu) <= float(threshold_cpu) else "fail"
        else:
            eval_expected["max_background_cpu_percent"] = "unknown"

        target_sr = reqs.get("target_sample_rate_hz")
        measured_sr = _get(json_data, ["measurements", "sample_rate_hz"], None)
        if _is_number(measured_sr) and _is_number(target_sr):
            eval_expected["target_sample_rate_hz"] = "pass" if int(measured_sr) == int(target_sr) else "fail"
        else:
            eval_expected["target_sample_rate_hz"] = "unknown"

        return eval_expected
    except Exception:
        return None


def _check_json_structure(data: Dict[str, Any]) -> bool:
    try:
        for k in ["os", "cpu", "memory", "disk", "battery", "audio", "measurements", "requirements"]:
            if k not in data or not isinstance(data[k], dict):
                return False

        if not isinstance(_get(data, ["os", "name"]), (str, type(None))):
            return False
        if not isinstance(_get(data, ["os", "version"]), (str, type(None))):
            return False

        if not isinstance(_get(data, ["cpu", "model"]), (str, type(None))):
            return False
        cores = _get(data, ["cpu", "cores_logical"])
        if not (isinstance(cores, int) or cores is None):
            return False

        if not _is_number(_get(data, ["memory", "total_gb"])):
            return False
        if not _is_number(_get(data, ["memory", "available_gb"])):
            return False

        if not isinstance(_get(data, ["disk", "mount"]), (str, type(None))):
            return False
        if not _is_number(_get(data, ["disk", "total_gb"])):
            return False
        if not _is_number(_get(data, ["disk", "free_gb"])):
            return False

        batt = _get(data, ["battery", "percent"])
        if not (_is_number(batt) or batt is None):
            return False

        devices = _get(data, ["audio", "devices_input"])
        if not (isinstance(devices, list) or devices is None):
            return False

        bg = _get(data, ["measurements", "background_cpu_percent"])
        if not (_is_number(bg) or bg is None):
            return False
        sr = _get(data, ["measurements", "sample_rate_hz"])
        if not (_is_number(sr) or sr is None):
            return False

        original = _get(data, ["requirements", "original"])
        evaluation = _get(data, ["requirements", "evaluation"])
        if not isinstance(original, dict):
            return False
        if not isinstance(evaluation, dict):
            return False
        required_eval_keys = [
            "min_free_disk_gb",
            "min_total_ram_gb",
            "preferred_os",
            "max_background_cpu_percent",
            "target_sample_rate_hz",
        ]
        for k in required_eval_keys:
            v = evaluation.get(k)
            if v not in ("pass", "fail", "unknown"):
                return False

        return True
    except Exception:
        return False


def _count_words(text: str) -> int:
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def _find_bullet_lines(text: str) -> List[str]:
    lines = text.splitlines()
    bullets = []
    for ln in lines:
        s = ln.lstrip()
        if s.startswith("- ") or s.startswith("* ") or s.startswith("•"):
            bullets.append(s)
    return bullets


def _line_has_status(line: str) -> bool:
    return bool(re.search(r"\b(pass|fail|unknown)\b", line, flags=re.IGNORECASE))


def _line_mentions_any(line: str, terms: List[str]) -> bool:
    ls = line.lower()
    return any(t in ls for t in terms)


def _check_report_contents(report_text: str, project_name: Optional[str], eval_map: Optional[Dict[str, str]], battery_present: bool) -> Tuple[bool, bool]:
    if report_text is None:
        return (False, False)

    lower = report_text.lower()
    has_project = project_name in report_text if isinstance(project_name, str) else False

    has_os = "os" in lower or "operating" in lower
    has_cpu = "cpu" in lower
    has_ram = ("ram" in lower) or ("memory" in lower)
    has_disk = ("disk" in lower) or ("free" in lower) or ("storage" in lower) or ("space" in lower)
    has_battery = ("battery" in lower)
    if battery_present:
        measurements_ok = has_os and has_cpu and has_ram and has_disk and has_battery
    else:
        measurements_ok = has_os and has_cpu and has_ram and has_disk

    has_project_and_measurements = has_project and measurements_ok

    bullets = _find_bullet_lines(report_text)
    if not bullets:
        return (has_project_and_measurements, False)

    def find_for(key: str, terms: List[str]) -> bool:
        status = (eval_map or {}).get(key, None)
        for b in bullets:
            if _line_mentions_any(b, terms) and _line_has_status(b):
                if status and re.search(rf"\b{re.escape(status)}\b", b, flags=re.IGNORECASE):
                    return True
                if not status:
                    return True
        return False

    checks_ok = True
    checks_ok &= find_for("min_free_disk_gb", ["disk", "free", "space", "storage"])
    checks_ok &= find_for("min_total_ram_gb", ["ram", "memory"])
    checks_ok &= find_for("preferred_os", ["os", "operating"])
    checks_ok &= find_for("max_background_cpu_percent", ["cpu", "background"])
    checks_ok &= find_for("target_sample_rate_hz", ["sample rate", "hz", "48k", "48000"])

    return (has_project_and_measurements, checks_ok)


def _approx_equal_int(a: Optional[float], b: int, tol: int = 1) -> bool:
    if a is None:
        return False
    try:
        return abs(int(round(float(a))) - b) <= tol
    except Exception:
        return False


def _check_message_highlights(message_text: str, data: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(message_text, str) or data is None:
        return False

    metrics = {
        "disk_free_gb": _get(data, ["disk", "free_gb"]),
        "total_ram_gb": _get(data, ["memory", "total_gb"]),
        "sample_rate_hz": _get(data, ["measurements", "sample_rate_hz"]),
        "background_cpu_percent": _get(data, ["measurements", "background_cpu_percent"]),
        "battery_percent": _get(data, ["battery", "percent"]),
    }

    available_categories = [k for k, v in metrics.items() if _is_number(v)]
    required_highlights = 2 if len(available_categories) >= 2 else max(1, len(available_categories))

    msg = message_text
    msg_lower = msg.lower()

    highlight_count = 0
    used_categories = set()

    gb_matches = re.findall(r"\b(\d+)\s*gb\b", msg_lower)
    ints_in_msg = [int(m) for m in gb_matches]
    if "disk_free_gb" in available_categories and "disk_free_gb" not in used_categories:
        val = metrics["disk_free_gb"]
        if any(_approx_equal_int(val, m) for m in ints_in_msg):
            highlight_count += 1
            used_categories.add("disk_free_gb")
    if "total_ram_gb" in available_categories and "total_ram_gb" not in used_categories:
        val = metrics["total_ram_gb"]
        if any(_approx_equal_int(val, m) for m in ints_in_msg):
            highlight_count += 1
            used_categories.add("total_ram_gb")

    hz_matches = re.findall(r"\b(\d{4,6})\s*hz\b", msg_lower)
    hz_vals = [int(h) for h in hz_matches]
    k_matches = re.findall(r"\b(\d+(?:\.\d+)?)\s*k\b", msg_lower)
    k_hz_vals = []
    for km in k_matches:
        try:
            kf = float(km)
            k_hz_vals.append(int(round(kf * 1000)))
        except Exception:
            pass
    if "sample_rate_hz" in available_categories and "sample_rate_hz" not in used_categories:
        val = metrics["sample_rate_hz"]
        try:
            val_int = int(round(float(val)))
        except Exception:
            val_int = None
        matched = False
        if val_int is not None:
            for m in hz_vals:
                if abs(m - val_int) <= 200:
                    matched = True
                    break
            if not matched:
                for m in k_hz_vals:
                    if abs(m - val_int) <= 200:
                        matched = True
                        break
        if matched:
            highlight_count += 1
            used_categories.add("sample_rate_hz")

    pct_matches = re.findall(r"\b(\d+)\s*%", msg_lower)
    pct_ints = [int(p) for p in pct_matches]
    if "background_cpu_percent" in available_categories and "background_cpu_percent" not in used_categories:
        val = metrics["background_cpu_percent"]
        if any(abs(int(round(float(val))) - p) <= 5 for p in pct_ints):
            highlight_count += 1
            used_categories.add("background_cpu_percent")
    if "battery_percent" in available_categories and "battery_percent" not in used_categories:
        val = metrics["battery_percent"]
        if any(abs(int(round(float(val))) - p) <= 5 for p in pct_ints):
            if "battery" in msg_lower:
                highlight_count += 1
                used_categories.add("battery_percent")

    return highlight_count >= required_highlights


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "status_json_exists_and_parseable": 0.0,
        "status_json_structure_fields": 0.0,
        "status_json_requirements_original_match_yaml": 0.0,
        "status_json_evaluation_consistency": 0.0,
        "report_exists_and_content": 0.0,
        "report_includes_project_and_checks": 0.0,
        "message_exists_and_length": 0.0,
        "message_includes_highlights_from_check": 0.0,
    }

    status_path = workspace / "outputs" / "system_status.json"
    report_path = workspace / "outputs" / "system_report.txt"
    message_path = workspace / "outputs" / "message_to_director.txt"
    yaml_path = workspace / "input" / "recording_requirements.yaml"

    status_json = _load_json(status_path)
    if status_json is not None:
        scores["status_json_exists_and_parseable"] = 1.0

    if status_json is not None and _check_json_structure(status_json):
        scores["status_json_structure_fields"] = 1.0

    yaml_dict = _parse_recording_requirements_yaml(yaml_path)
    if yaml_dict is not None and status_json is not None:
        original = _get(status_json, ["requirements", "original"], None)
        if isinstance(original, dict) and original == yaml_dict:
            scores["status_json_requirements_original_match_yaml"] = 1.0

    if yaml_dict is not None and status_json is not None:
        expected_eval = _status_expected_from_yaml_and_measured(yaml_dict, status_json)
        actual_eval = _get(status_json, ["requirements", "evaluation"], None)
        if isinstance(expected_eval, dict) and isinstance(actual_eval, dict):
            keys = [
                "min_free_disk_gb",
                "min_total_ram_gb",
                "preferred_os",
                "max_background_cpu_percent",
                "target_sample_rate_hz",
            ]
            consistent = all(actual_eval.get(k) == expected_eval.get(k) for k in keys)
            if consistent:
                scores["status_json_evaluation_consistency"] = 1.0

    report_text = _read_text(report_path)
    if report_text is not None:
        scores["report_exists_and_content"] = 1.0

    battery_percent = _get(status_json or {}, ["battery", "percent"], None)
    battery_present = _is_number(battery_percent)
    project_name = yaml_dict.get("project") if isinstance(yaml_dict, dict) else None
    eval_map = _get(status_json or {}, ["requirements", "evaluation"], None) if isinstance(status_json, dict) else None
    has_proj_meas, has_bullets = _check_report_contents(report_text or "", project_name, eval_map if isinstance(eval_map, dict) else None, battery_present)
    if has_proj_meas:
        scores["report_includes_project_and_checks"] = 0.5
    if has_bullets:
        scores["report_includes_project_and_checks"] += 0.5
        if scores["report_includes_project_and_checks"] > 1.0:
            scores["report_includes_project_and_checks"] = 1.0

    message_text = _read_text(message_path)
    if message_text is not None:
        words = _count_words(message_text)
        if words <= 160 and words > 0:
            scores["message_exists_and_length"] = 1.0

    if message_text is not None and status_json is not None:
        if _check_message_highlights(message_text, status_json):
            scores["message_includes_highlights_from_check"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()