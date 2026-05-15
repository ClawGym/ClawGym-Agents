import json
import sys
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List


def _read_text(path: Path) -> Tuple[bool, Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None
        text = path.read_text(encoding="utf-8", errors="replace")
        return True, text
    except Exception:
        return False, None


def _load_json(path: Path) -> Tuple[bool, Optional[Any]]:
    ok, text = _read_text(path)
    if not ok or text is None:
        return False, None
    try:
        return True, json.loads(text)
    except Exception:
        return False, None


def _normalize_lines(text: str) -> List[str]:
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    return norm.split("\n") if norm == "" else norm.rstrip("\n").split("\n")


def _expected_mock_output(profile: str) -> List[str]:
    if profile == "1080p60":
        return [
            "[CHECK] Profile: 1080p60",
            "[CHECK] CPU logical cores: 4",
            "[CHECK] CPU baseline score: 3500",
            "[CHECK] GPU acceleration: available",
            "[CHECK] Video decode h264: supported",
            "[CHECK] Network bandwidth Mbps: 28",
            "[CHECK] Network jitter ms: 18",
            "[WARN] Dropped frames in 60fps test: 7",
            "[ERROR] Render queue underruns: 2",
            "[INFO] End of diagnostics",
        ]
    elif profile == "720p60":
        return [
            "[CHECK] Profile: 720p60",
            "[CHECK] CPU logical cores: 4",
            "[CHECK] CPU baseline score: 3500",
            "[CHECK] GPU acceleration: available",
            "[CHECK] Video decode h264: supported",
            "[CHECK] Network bandwidth Mbps: 28",
            "[CHECK] Network jitter ms: 18",
            "[WARN] Dropped frames in 60fps test: 2",
            "[INFO] End of diagnostics",
        ]
    else:
        return []


def _parse_raw_diagnostics(lines: List[str]) -> Tuple[Dict[str, Any], List[str], List[str]]:
    metrics: Dict[str, Any] = {
        "cpu_cores": None,
        "cpu_score": None,
        "bandwidth_mbps": None,
        "jitter_ms": None,
        "dropped_frames": None,
        "gpu_acceleration": None,
        "h264_decode_supported": None,
        "warn_count": 0,
        "error_count": 0,
    }
    warnings: List[str] = []
    errors: List[str] = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("[CHECK] CPU logical cores:"):
            try:
                metrics["cpu_cores"] = int(s.split(":", 1)[1].strip())
            except Exception:
                pass
        elif s.startswith("[CHECK] CPU baseline score:"):
            try:
                metrics["cpu_score"] = int(s.split(":", 1)[1].strip())
            except Exception:
                pass
        elif s.startswith("[CHECK] GPU acceleration:"):
            val = s.split(":", 1)[1].strip().lower()
            metrics["gpu_acceleration"] = (val == "available" or val == "enabled" or val == "true")
        elif s.startswith("[CHECK] Video decode h264:"):
            val = s.split(":", 1)[1].strip().lower()
            metrics["h264_decode_supported"] = (val == "supported" or val == "yes" or val == "true")
        elif s.startswith("[CHECK] Network bandwidth Mbps:"):
            try:
                metrics["bandwidth_mbps"] = int(s.split(":", 1)[1].strip())
            except Exception:
                pass
        elif s.startswith("[CHECK] Network jitter ms:"):
            try:
                metrics["jitter_ms"] = int(s.split(":", 1)[1].strip())
            except Exception:
                pass
        elif s.startswith("[WARN]"):
            msg = s[len("[WARN]"):].strip()
            warnings.append(msg)
            metrics["warn_count"] += 1
            lower = msg.lower()
            if "dropped frames" in lower and ":" in msg:
                try:
                    num = int(msg.split(":", 1)[1].strip())
                    metrics["dropped_frames"] = num
                except Exception:
                    pass
        elif s.startswith("[ERROR]"):
            msg = s[len("[ERROR]"):].strip()
            errors.append(msg)
            metrics["error_count"] += 1
    return metrics, warnings, errors


def _load_thresholds_yaml(yaml_path: Path) -> Tuple[bool, Optional[Dict[str, Dict[str, int]]]]:
    ok, text = _read_text(yaml_path)
    if not ok or text is None:
        return False, None
    try:
        raw = text.replace("\r\n", "\n").replace("\r", "\n")
        if "\\n" in raw and "\n" not in raw.strip():
            raw = raw.replace("\\n", "\n")
        lines = [ln.rstrip() for ln in raw.split("\n")]
        profiles: Dict[str, Dict[str, int]] = {}
        current_profile: Optional[str] = None
        in_profiles = False
        for ln in lines:
            if ln.strip().startswith("profiles:"):
                in_profiles = True
                current_profile = None
                continue
            if not in_profiles:
                continue
            stripped = ln.strip()
            if stripped.startswith('"1080p60":') or stripped.startswith("'1080p60':"):
                current_profile = "1080p60"
                profiles[current_profile] = {}
                continue
            if stripped.startswith('"720p60":') or stripped.startswith("'720p60':"):
                current_profile = "720p60"
                profiles[current_profile] = {}
                continue
            if stripped.startswith("notes:"):
                current_profile = None
                in_profiles = False
                continue
            if current_profile:
                if "min_bandwidth_mbps:" in stripped:
                    try:
                        val = int(stripped.split(":", 1)[1].strip())
                        profiles[current_profile]["min_bandwidth_mbps"] = val
                    except Exception:
                        pass
                elif "max_dropped_frames:" in stripped:
                    try:
                        val = int(stripped.split(":", 1)[1].strip())
                        profiles[current_profile]["max_dropped_frames"] = val
                    except Exception:
                        pass
                elif "max_jitter_ms:" in stripped:
                    try:
                        val = int(stripped.split(":", 1)[1].strip())
                        profiles[current_profile]["max_jitter_ms"] = val
                    except Exception:
                        pass
        for prof in ["1080p60", "720p60"]:
            if prof not in profiles:
                return False, None
            for key in ["min_bandwidth_mbps", "max_dropped_frames", "max_jitter_ms"]:
                if key not in profiles[prof] or not isinstance(profiles[prof][key], int):
                    return False, None
        return True, profiles
    except Exception:
        return False, None


def _compute_ready(metrics: Dict[str, Any], thresholds: Dict[str, int]) -> Tuple[bool, List[str]]:
    failed_reasons: List[str] = []
    if metrics.get("error_count", 0) != 0:
        failed_reasons.append("errors_present")
    bw = metrics.get("bandwidth_mbps")
    df = metrics.get("dropped_frames")
    jm = metrics.get("jitter_ms")
    if isinstance(bw, int) and isinstance(df, int) and isinstance(jm, int):
        if bw < thresholds.get("min_bandwidth_mbps", 0):
            failed_reasons.append("min_bandwidth_mbps")
        if df > thresholds.get("max_dropped_frames", 0):
            failed_reasons.append("max_dropped_frames")
        if jm > thresholds.get("max_jitter_ms", 0):
            failed_reasons.append("max_jitter_ms")
    else:
        failed_reasons.extend(["min_bandwidth_mbps", "max_dropped_frames", "max_jitter_ms"])
    ready = len(failed_reasons) == 0
    return ready, failed_reasons


def _find_profile_status_in_report(report_text: str, profile: str) -> Optional[bool]:
    lines = _normalize_lines(report_text)
    for idx, ln in enumerate(lines):
        if profile in ln:
            window = " ".join(lines[idx: idx + 4]).lower()
            if "not ready" in window:
                return False
            if "ready" in window:
                return True
    low_all = report_text.lower()
    if profile in report_text and "not ready" in low_all:
        return False
    if profile in report_text and "ready" in low_all:
        return True
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "raw_1080p60_output_captured_correct": 0.0,
        "raw_720p60_output_captured_correct": 0.0,
        "readiness_json_exists_and_schema": 0.0,
        "json_metrics_match_raw": 0.0,
        "thresholds_source_field_correct": 0.0,
        "readiness_flags_match_thresholds": 0.0,
        "pretty_json_matches_json_tool": 0.0,
        "validation_errors_file_correct": 0.0,
        "report_overview_mentions_soccer_and_60fps": 0.0,
        "report_profiles_status_match_json": 0.0,
        "report_includes_metrics_and_issues": 0.0,
        "report_contains_actionable_recommendation_if_not_ready": 0.0,
    }

    raw_1080_path = workspace / "artifacts" / "raw" / "1080p60.txt"
    raw_720_path = workspace / "artifacts" / "raw" / "720p60.txt"

    ok1080, raw1080_text = _read_text(raw_1080_path)
    ok720, raw720_text = _read_text(raw_720_path)

    expected_1080_lines = _expected_mock_output("1080p60")
    expected_720_lines = _expected_mock_output("720p60")

    if ok1080 and raw1080_text is not None:
        actual_lines_1080 = _normalize_lines(raw1080_text)
        if actual_lines_1080 == expected_1080_lines:
            scores["raw_1080p60_output_captured_correct"] = 1.0

    if ok720 and raw720_text is not None:
        actual_lines_720 = _normalize_lines(raw720_text)
        if actual_lines_720 == expected_720_lines:
            scores["raw_720p60_output_captured_correct"] = 1.0

    raw_metrics_map: Dict[str, Dict[str, Any]] = {}
    raw_warns_map: Dict[str, List[str]] = {}
    raw_errors_map: Dict[str, List[str]] = {}

    if ok1080 and raw1080_text is not None:
        m, w, e = _parse_raw_diagnostics(_normalize_lines(raw1080_text))
        raw_metrics_map["1080p60"] = m
        raw_warns_map["1080p60"] = w
        raw_errors_map["1080p60"] = e
    if ok720 and raw720_text is not None:
        m, w, e = _parse_raw_diagnostics(_normalize_lines(raw720_text))
        raw_metrics_map["720p60"] = m
        raw_warns_map["720p60"] = w
        raw_errors_map["720p60"] = e

    readiness_json_path = workspace / "artifacts" / "stream_readiness.json"
    json_ok, readiness_obj = _load_json(readiness_json_path)

    profiles_map_from_json: Dict[str, Any] = {}
    if json_ok and isinstance(readiness_obj, dict):
        thresholds_source = readiness_obj.get("thresholds_source")
        profiles = readiness_obj.get("profiles")
        schema_valid = True
        if thresholds_source is None or not isinstance(profiles, list):
            schema_valid = False
        else:
            for prof in profiles:
                if not isinstance(prof, dict):
                    schema_valid = False
                    break
                name = prof.get("name")
                metrics = prof.get("metrics")
                warnings = prof.get("warnings")
                errors = prof.get("errors")
                ready = prof.get("ready")
                failed_reasons = prof.get("failed_reasons")
                if not isinstance(name, str):
                    schema_valid = False
                    break
                required_metric_keys = [
                    "cpu_cores",
                    "cpu_score",
                    "bandwidth_mbps",
                    "jitter_ms",
                    "dropped_frames",
                    "gpu_acceleration",
                    "h264_decode_supported",
                    "warn_count",
                    "error_count",
                ]
                if not isinstance(metrics, dict):
                    schema_valid = False
                    break
                for k in required_metric_keys:
                    if k not in metrics:
                        schema_valid = False
                        break
                if not schema_valid:
                    break
                int_keys = ["cpu_cores", "cpu_score", "bandwidth_mbps", "jitter_ms", "dropped_frames", "warn_count", "error_count"]
                bool_keys = ["gpu_acceleration", "h264_decode_supported"]
                for k in int_keys:
                    if not isinstance(metrics.get(k), int):
                        schema_valid = False
                        break
                if not schema_valid:
                    break
                for k in bool_keys:
                    if not isinstance(metrics.get(k), bool):
                        schema_valid = False
                        break
                if not isinstance(warnings, list) or not all(isinstance(x, str) for x in warnings):
                    schema_valid = False
                    break
                if not isinstance(errors, list) or not all(isinstance(x, str) for x in errors):
                    schema_valid = False
                    break
                if not isinstance(ready, bool):
                    schema_valid = False
                    break
                if not isinstance(failed_reasons, list) or not all(isinstance(x, str) for x in failed_reasons):
                    schema_valid = False
                    break
                if metrics.get("warn_count") != len(warnings):
                    schema_valid = False
                    break
                if metrics.get("error_count") != len(errors):
                    schema_valid = False
                    break
                profiles_map_from_json[name] = prof
        if schema_valid and set(profiles_map_from_json.keys()) == {"1080p60", "720p60"}:
            scores["readiness_json_exists_and_schema"] = 1.0

        if thresholds_source == "input/stream_thresholds.yaml":
            scores["thresholds_source_field_correct"] = 1.0

    metrics_match_all = True
    if scores["readiness_json_exists_and_schema"] == 1.0 and raw_metrics_map:
        for prof_name in ["1080p60", "720p60"]:
            if prof_name not in profiles_map_from_json or prof_name not in raw_metrics_map:
                metrics_match_all = False
                break
            prof_json = profiles_map_from_json[prof_name]
            metrics_json = prof_json.get("metrics", {})
            m_raw = raw_metrics_map[prof_name]
            for k in ["cpu_cores", "cpu_score", "bandwidth_mbps", "jitter_ms", "dropped_frames",
                      "gpu_acceleration", "h264_decode_supported"]:
                if metrics_json.get(k) != m_raw.get(k):
                    metrics_match_all = False
                    break
            if not metrics_match_all:
                break
            warnings_json = prof_json.get("warnings", [])
            errors_json = prof_json.get("errors", [])
            raw_warn_msgs = raw_warns_map.get(prof_name, [])
            raw_err_msgs = raw_errors_map.get(prof_name, [])
            def list_matches(raw_msgs: List[str], lst: List[str], prefix: str) -> bool:
                if len(raw_msgs) != len(lst):
                    return False
                for a, b in zip(raw_msgs, lst):
                    if not (b == a or b == f"{prefix} {a}"):
                        return False
                return True
            if not list_matches(raw_warn_msgs, warnings_json, "[WARN]"):
                metrics_match_all = False
                break
            if not list_matches(raw_err_msgs, errors_json, "[ERROR]"):
                metrics_match_all = False
                break
    else:
        metrics_match_all = False

    if metrics_match_all:
        scores["json_metrics_match_raw"] = 1.0

    thresholds_ok, thresholds = _load_thresholds_yaml(workspace / "input" / "stream_thresholds.yaml")

    readiness_flags_ok = True
    if scores["readiness_json_exists_and_schema"] == 1.0 and thresholds_ok and raw_metrics_map:
        for prof_name in ["1080p60", "720p60"]:
            prof_json = profiles_map_from_json.get(prof_name)
            m_raw = raw_metrics_map.get(prof_name)
            if prof_json is None or m_raw is None:
                readiness_flags_ok = False
                break
            expected_ready, expected_failed_reasons = _compute_ready(m_raw, thresholds.get(prof_name, {}))
            if prof_json.get("ready") != expected_ready:
                readiness_flags_ok = False
                break
            fr = prof_json.get("failed_reasons", [])
            if expected_ready and len(fr) != 0:
                readiness_flags_ok = False
                break
            if not expected_ready:
                if len(fr) == 0:
                    readiness_flags_ok = False
                    break
                if m_raw.get("error_count", 0) > 0 and "errors_present" not in fr:
                    readiness_flags_ok = False
                    break
    else:
        readiness_flags_ok = False

    if readiness_flags_ok:
        scores["readiness_flags_match_thresholds"] = 1.0

    pretty_path = workspace / "artifacts" / "stream_readiness.pretty.json"
    val_err_path = workspace / "artifacts" / "validation_errors.txt"

    pretty_ok, pretty_text = _read_text(pretty_path)
    original_valid = json_ok
    pretty_matches = False
    if json_ok and readiness_obj is not None and pretty_ok and pretty_text is not None:
        try:
            expected_pretty = json.dumps(readiness_obj, indent=4, sort_keys=True) + "\n"
            if pretty_text == expected_pretty:
                pretty_matches = True
        except Exception:
            pretty_matches = False

    if pretty_matches:
        scores["pretty_json_matches_json_tool"] = 1.0

    val_ok, val_text = _read_text(val_err_path)
    if val_ok and val_text is not None:
        if original_valid:
            if val_text.strip() == "":
                scores["validation_errors_file_correct"] = 1.0
        else:
            if val_text.strip() != "":
                scores["validation_errors_file_correct"] = 1.0

    report_path = workspace / "artifacts" / "stream_readiness_report.md"
    rep_ok, rep_text = _read_text(report_path)

    if rep_ok and rep_text is not None:
        low = rep_text.lower()
        mentions_soccer = "soccer" in low
        mentions_60fps = ("60 fps" in low) or ("60fps" in low)
        if mentions_soccer and mentions_60fps:
            scores["report_overview_mentions_soccer_and_60fps"] = 1.0

        profiles_status_ok = False
        if scores["readiness_json_exists_and_schema"] == 1.0:
            status_1080 = _find_profile_status_in_report(rep_text, "1080p60")
            status_720 = _find_profile_status_in_report(rep_text, "720p60")
            pj_1080 = profiles_map_from_json["1080p60"]["ready"]
            pj_720 = profiles_map_from_json["720p60"]["ready"]
            if status_1080 is not None and status_720 is not None:
                if (status_1080 == pj_1080) and (status_720 == pj_720):
                    profiles_status_ok = True
        if profiles_status_ok:
            scores["report_profiles_status_match_json"] = 1.0

        has_bandwidth = "bandwidth" in low
        has_jitter = "jitter" in low
        has_dropped = "dropped" in low
        has_underrun = ("underrun" in low)
        if has_bandwidth and has_jitter and has_dropped and has_underrun:
            scores["report_includes_metrics_and_issues"] = 1.0

        any_not_ready = False
        if scores["readiness_json_exists_and_schema"] == 1.0:
            any_not_ready = any(not p["ready"] for p in profiles_map_from_json.values())
        actionable_phrases = [
            "ethernet",
            "close background",
            "close apps",
            "close programs",
            "hardware acceleration",
            "enable hardware",
            "use ethernet",
            "try 720p",
            "lower resolution",
            "wired",
            "disable other downloads",
            "stop downloads",
            "reduce quality",
        ]
        has_actionable = any(phrase in low for phrase in actionable_phrases)
        if any_not_ready and has_actionable:
            scores["report_contains_actionable_recommendation_if_not_ready"] = 1.0
        elif not any_not_ready:
            scores["report_contains_actionable_recommendation_if_not_ready"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()