import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(_read_text(path) or "")
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the expected config:
    keys: min_disk_gb: number
          min_build_tools_versions: [list of strings]
          log_patterns: [list of strings]
    Also supports block list form:
      key:
        - item1
        - item2
    """
    content = _read_text(path)
    if content is None:
        return None
    lines = content.splitlines()
    result: Dict[str, Any] = {}
    i = 0
    n = len(lines)
    current_key = None
    while i < n:
        raw = lines[i]
        line = raw.split("#", 1)[0].rstrip()
        i += 1
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            # list item without an active list key is invalid for our simple parser
            if current_key is None:
                return None
            item_val = line.strip()[2:]
            result[current_key].append(_strip_quotes(item_val))
            continue
        if ":" in line:
            left, right = line.split(":", 1)
            key = left.strip()
            val = right.strip()
            current_key = None
            if val == "":
                # Expect a block list
                # Lookahead for "- " items
                lst: List[str] = []
                # Gather following indented "- " items
                while i < n:
                    peek_raw = lines[i]
                    peek = peek_raw.split("#", 1)[0].rstrip()
                    if not peek.strip():
                        i += 1
                        continue
                    if peek.lstrip().startswith("- "):
                        lst.append(_strip_quotes(peek.strip()[2:]))
                        i += 1
                        continue
                    # stop block list
                    break
                result[key] = lst
            else:
                # scalar value
                sval = _strip_quotes(val)
                # Try to parse number
                if re.fullmatch(r"-?\d+(\.\d+)?", sval):
                    try:
                        if "." in sval:
                            result[key] = float(sval)
                        else:
                            # Even if integer, we expect number; keep as float for consistency
                            result[key] = float(int(sval))
                        current_key = None
                        continue
                    except Exception:
                        pass
                result[key] = sval
        else:
            # unsupported line
            continue
    return result


def _compute_log_metrics(workspace: Path, patterns: List[str]) -> Tuple[int, int, Dict[str, int]]:
    toast_lines = 0
    error_lines = 0
    pattern_counts: Dict[str, int] = {p: 0 for p in patterns}
    log_path = workspace / "logs" / "logcat_sample.txt"
    text = _read_text(log_path) or ""
    for line in text.splitlines():
        if "Toast" in line:
            toast_lines += 1
        # count error lines: either line starts with E/ after trimming or contains " E/"
        if line.lstrip().startswith("E/") or " E/" in line:
            error_lines += 1
        for p in patterns:
            if p in line:
                pattern_counts[p] += 1
    return toast_lines, error_lines, pattern_counts


def _parse_build_log(workspace: Path) -> Tuple[str, Optional[str]]:
    status = "UNKNOWN"
    duration: Optional[str] = None
    build_path = workspace / "logs" / "gradle_build.log"
    text = _read_text(build_path)
    if text is None:
        return status, duration
    for line in text.splitlines():
        if "BUILD SUCCESSFUL" in line:
            status = "SUCCESS"
            # capture duration like "in 1m 12s"
            m = re.search(r"\bin\s+(.+)$", line)
            duration = m.group(1).strip() if m else None
        elif "BUILD FAILED" in line:
            status = "FAILED"
            m = re.search(r"\bin\s+(.+)$", line)
            duration = m.group(1).strip() if m else None
    return status, duration


def _dict_has_exact_keys(d: Any, keys: List[str]) -> bool:
    if not isinstance(d, dict):
        return False
    return set(d.keys()) == set(keys)


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _contains_bool_text(s: str, value: Optional[bool]) -> bool:
    if value is None:
        return True
    s_low = s.lower()
    if value:
        return ("true" in s_low) or ("yes" in s_low)
    else:
        return ("false" in s_low) or ("no" in s_low)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_yaml_exists": 0.0,
        "config_yaml_valid_and_required_keys": 0.0,
        "inspect_script_exists": 0.0,
        "inspect_script_references_paths_and_message": 0.0,
        "system_status_json_exists": 0.0,
        "system_status_json_valid_shape": 0.0,
        "log_summary_correct_counts": 0.0,
        "build_log_parsed_correctly": 0.0,
        "disk_ok_consistent_with_threshold": 0.0,
        "status_notifier_no_toast": 0.0,
        "status_notifier_log_replacement_and_comment": 0.0,
        "slack_update_exists": 0.0,
        "slack_update_mentions_required_items": 0.0,
        "slack_update_sentence_count": 0.0,
    }

    # 1) Validate config/checks.yaml
    config_path = workspace / "config" / "checks.yaml"
    config = None
    if config_path.exists() and config_path.is_file():
        scores["config_yaml_exists"] = 1.0
        config = _parse_simple_yaml(config_path)
        if isinstance(config, dict):
            required_keys_present = all(k in config for k in ["min_disk_gb", "min_build_tools_versions", "log_patterns"])
            types_ok = False
            if required_keys_present:
                min_disk = config.get("min_disk_gb")
                mbt = config.get("min_build_tools_versions")
                lp = config.get("log_patterns")
                min_disk_ok = _is_number(min_disk)
                mbt_ok = isinstance(mbt, list) and all(isinstance(x, str) for x in mbt)
                lp_ok = isinstance(lp, list) and all(isinstance(x, str) for x in lp)
                types_ok = min_disk_ok and mbt_ok and lp_ok
            if required_keys_present and types_ok:
                scores["config_yaml_valid_and_required_keys"] = 1.0
        # else invalid remains 0.0

    # 2) Validate tools/inspect_android_env.py existence and references
    script_path = workspace / "tools" / "inspect_android_env.py"
    if script_path.exists() and script_path.is_file():
        scores["inspect_script_exists"] = 1.0
        script_text = _read_text(script_path) or ""
        refs_ok = (
            "config/checks.yaml" in script_text
            and "out/system_status.json" in script_text
            and "Status report written to out/system_status.json" in script_text
        )
        if refs_ok:
            scores["inspect_script_references_paths_and_message"] = 1.0

    # 3) Validate out/system_status.json existence and shape
    status_path = workspace / "out" / "system_status.json"
    status_json = _load_json(status_path)
    if status_json is not None:
        scores["system_status_json_exists"] = 1.0
        # exact top-level keys
        expected_top = [
            "os",
            "java",
            "android_sdk",
            "adb",
            "disk",
            "gradle_cache",
            "log_summary",
            "build_log",
        ]
        shape_ok = _dict_has_exact_keys(status_json, expected_top)
        if shape_ok:
            # Check nested structures and types
            ok = True
            # os
            os_obj = status_json.get("os")
            ok &= isinstance(os_obj, dict) and "uname" in os_obj and isinstance(os_obj.get("uname"), str)
            # java
            java_obj = status_json.get("java")
            ok &= isinstance(java_obj, dict) and _dict_has_exact_keys(java_obj, ["present", "version"])
            if ok:
                ok &= isinstance(java_obj.get("present"), bool)
                v = java_obj.get("version")
                ok &= (v is None) or isinstance(v, str)
            # android_sdk
            asdk_obj = status_json.get("android_sdk")
            ok &= isinstance(asdk_obj, dict) and _dict_has_exact_keys(
                asdk_obj,
                ["env_var", "path", "platforms_exists", "build_tools_exists", "min_build_tools_satisfied"],
            )
            if ok:
                for k in ["env_var", "path"]:
                    vv = asdk_obj.get(k)
                    ok &= (vv is None) or isinstance(vv, str)
                for k in ["platforms_exists", "build_tools_exists", "min_build_tools_satisfied"]:
                    vv = asdk_obj.get(k)
                    ok &= (vv is None) or isinstance(vv, bool)
            # adb
            adb_obj = status_json.get("adb")
            ok &= isinstance(adb_obj, dict) and _dict_has_exact_keys(adb_obj, ["present", "server_running", "connected_devices"])
            if ok:
                ok &= isinstance(adb_obj.get("present"), bool)
                srv = adb_obj.get("server_running")
                ok &= (srv is None) or isinstance(srv, bool)
                cd = adb_obj.get("connected_devices")
                ok &= isinstance(cd, int) and cd >= 0
            # disk
            disk_obj = status_json.get("disk")
            ok &= isinstance(disk_obj, dict) and _dict_has_exact_keys(disk_obj, ["free_gb", "disk_ok"])
            if ok:
                ok &= _is_number(disk_obj.get("free_gb"))
                ok &= isinstance(disk_obj.get("disk_ok"), bool)
            # gradle_cache
            gc_obj = status_json.get("gradle_cache")
            ok &= isinstance(gc_obj, dict) and _dict_has_exact_keys(gc_obj, ["path", "size_mb"])
            if ok:
                p = gc_obj.get("path")
                ok &= (p is None) or isinstance(p, str)
                s = gc_obj.get("size_mb")
                ok &= (s is None) or _is_number(s)
            # log_summary
            ls_obj = status_json.get("log_summary")
            ok &= isinstance(ls_obj, dict) and _dict_has_exact_keys(ls_obj, ["toast_lines", "error_lines", "pattern_counts"])
            if ok:
                ok &= isinstance(ls_obj.get("toast_lines"), int) and ls_obj.get("toast_lines") >= 0
                ok &= isinstance(ls_obj.get("error_lines"), int) and ls_obj.get("error_lines") >= 0
                ok &= isinstance(ls_obj.get("pattern_counts"), dict)
            # build_log
            bl_obj = status_json.get("build_log")
            ok &= isinstance(bl_obj, dict) and _dict_has_exact_keys(bl_obj, ["status", "duration"])
            if ok:
                ok &= bl_obj.get("status") in ("SUCCESS", "FAILED", "UNKNOWN")
                d = bl_obj.get("duration")
                ok &= (d is None) or isinstance(d, str)
            if ok:
                scores["system_status_json_valid_shape"] = 1.0

    # 4) Cross-check log summary counts using config patterns
    if (config is not None) and (status_json is not None) and isinstance(config.get("log_patterns"), list):
        patterns = list(config.get("log_patterns"))
        toast_c, error_c, pat_counts = _compute_log_metrics(workspace, patterns)
        ls_obj2 = status_json.get("log_summary") if isinstance(status_json, dict) else None
        ok_logs = False
        if isinstance(ls_obj2, dict):
            ok_logs = (
                ls_obj2.get("toast_lines") == toast_c
                and ls_obj2.get("error_lines") == error_c
                and isinstance(ls_obj2.get("pattern_counts"), dict)
                and all(ls_obj2["pattern_counts"].get(p) == pat_counts.get(p, 0) for p in patterns)
                and set(ls_obj2["pattern_counts"].keys()) == set(patterns)
            )
        if ok_logs:
            scores["log_summary_correct_counts"] = 1.0

    # 5) Cross-check build log parsing
    if status_json is not None:
        status_expected, duration_expected = _parse_build_log(workspace)
        bl_obj2 = status_json.get("build_log") if isinstance(status_json, dict) else None
        ok_bl = False
        if isinstance(bl_obj2, dict):
            ok_bl = bl_obj2.get("status") == status_expected and bl_obj2.get("duration") == duration_expected
        if ok_bl:
            scores["build_log_parsed_correctly"] = 1.0

    # 6) Disk OK consistency check with config threshold using JSON's free_gb
    if (config is not None) and (status_json is not None):
        min_disk = config.get("min_disk_gb")
        disk_obj2 = status_json.get("disk") if isinstance(status_json, dict) else None
        if _is_number(min_disk) and isinstance(disk_obj2, dict) and _is_number(disk_obj2.get("free_gb")) and isinstance(disk_obj2.get("disk_ok"), bool):
            computed_ok = float(disk_obj2.get("free_gb")) >= float(min_disk)
            if computed_ok == disk_obj2.get("disk_ok"):
                scores["disk_ok_consistent_with_threshold"] = 1.0

    # 7) Validate StatusNotifier.kt updates
    notifier_path = workspace / "app" / "src" / "main" / "java" / "com" / "example" / "StatusNotifier.kt"
    text = _read_text(notifier_path)
    if text is not None:
        # No Toast usage anywhere
        if "Toast" not in text:
            scores["status_notifier_no_toast"] = 1.0
        # Comment line, function signatures unchanged, and Log.d replacements
        comment_ok = 'Replaced Toast with Log to avoid UI popups.' in text
        sig1_ok = "fun showStatus(context: Context, message: String)" in text
        sig2_ok = "fun notifyError(context: Context, message: String)" in text
        log_calls = len(re.findall(r"\bLog\.d\s*\(", text)) >= 2
        # Heuristic checks that showStatus logs message and notifyError logs "Error: " and message
        def _extract_block(src: str, func_sig: str) -> str:
            start = src.find(func_sig)
            if start == -1:
                return ""
            # Take from start to next "fun " or end
            rest = src[start:]
            m = re.search(r"\n\s*fun\s", rest[1:])
            end = start + 1 + m.start() if m else len(src)
            return src[start:end]

        show_block = _extract_block(text, "fun showStatus(context: Context, message: String)")
        notify_block = _extract_block(text, "fun notifyError(context: Context, message: String)")
        show_has_message = ("Log.d" in show_block) and ("message" in show_block)
        notify_has_error_and_message = ("Log.d" in notify_block) and (("Error:" in notify_block) or ("Error" in notify_block)) and ("message" in notify_block)

        if comment_ok and sig1_ok and sig2_ok and log_calls and show_has_message and notify_has_error_and_message:
            scores["status_notifier_log_replacement_and_comment"] = 1.0

    # 8) Validate slack update
    slack_path = workspace / "out" / "slack_update.txt"
    slack_text = _read_text(slack_path)
    if slack_text is not None and slack_text.strip():
        scores["slack_update_exists"] = 1.0
        # Sentence count 4–6 sentences (count ., !, ?)
        sent_count = len(re.findall(r"[.!?](\s|$)", slack_text))
        if 4 <= sent_count <= 6:
            scores["slack_update_sentence_count"] = 1.0

        # Mentions required items based on system_status.json
        mentions_ok = False
        if status_json is not None and isinstance(status_json, dict):
            try:
                # disk_ok
                disk_ok_val = status_json["disk"]["disk_ok"]
                java_version = status_json["java"]["version"]
                adb_present = status_json["adb"]["present"]
                adb_devices = status_json["adb"]["connected_devices"]
                bl_status = status_json["build_log"]["status"]
                bl_duration = status_json["build_log"]["duration"]
                toast_lines = status_json["log_summary"]["toast_lines"]
                error_lines = status_json["log_summary"]["error_lines"]
                # Conditions:
                conds = []
                # Include path
                conds.append("out/system_status.json" in slack_text)
                # Mention Toast removal
                toast_removal_ok = ("Replaced Toast with Log" in slack_text) or (("Toast" in slack_text) and ("Log" in slack_text) and ("StatusNotifier.kt" in slack_text))
                conds.append(toast_removal_ok)
                # disk_ok presence (boolean text) and reference to disk
                conds.append(("disk" in slack_text.lower()) and _contains_bool_text(slack_text, disk_ok_val))
                # java.version or "missing"
                if java_version is None:
                    conds.append("missing" in slack_text.lower())
                else:
                    conds.append(str(java_version) in slack_text)
                # adb.present and adb.connected_devices
                conds.append(("adb" in slack_text.lower()) and (str(adb_devices) in slack_text))
                # For present, ensure some boolean text exists
                conds.append(_contains_bool_text(slack_text, adb_present))
                # build_log.status and duration (if present)
                conds.append(bl_status in slack_text)
                if bl_duration is not None:
                    conds.append(str(bl_duration) in slack_text)
                # counts of toast_lines and error_lines
                conds.append(str(toast_lines) in slack_text)
                conds.append(str(error_lines) in slack_text)
                mentions_ok = all(conds)
            except Exception:
                mentions_ok = False
        if mentions_ok:
            scores["slack_update_mentions_required_items"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()