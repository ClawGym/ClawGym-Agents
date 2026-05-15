import json
import re
import sys
import csv
from pathlib import Path
from typing import Optional, Dict, Any, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            required = {"artist", "title", "filepath", "duration_seconds"}
            if not required.issubset(set(reader.fieldnames or [])):
                return None
            for r in rows:
                try:
                    int(r["duration_seconds"])
                except Exception:
                    return None
            return rows
    except Exception:
        return None


def _parse_simple_yaml_map(text: str) -> Optional[Dict[str, Any]]:
    try:
        root: Dict[str, Any] = {}
        stack: List[tuple[int, Dict[str, Any]]] = [(-1, root)]

        def parse_value(val: str) -> Any:
            v = val.strip()
            if v == "":
                return None
            if not (v.startswith('"') or v.startswith("'")):
                hash_pos = v.find(" #")
                if hash_pos != -1:
                    v = v[:hash_pos].rstrip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                q = v[0]
                inner = v[1:-1]
                if q == '"':
                    inner = inner.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")
                else:
                    inner = inner.replace("\\'", "'")
                return inner
            return v

        for raw_line in text.splitlines():
            if not raw_line.strip() or raw_line.strip().startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            line = raw_line.rstrip()
            m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.*)$", line)
            if not m:
                return None
            key = m.group(1)
            rest = m.group(2)
            while stack and indent <= stack[-1][0]:
                stack.pop()
            if not stack:
                return None
            parent = stack[-1][1]
            val = parse_value(rest)
            if val is None:
                child: Dict[str, Any] = {}
                parent[key] = child
                stack.append((indent, child))
            else:
                parent[key] = val
        return root
    except Exception:
        return None


def _get_first_nonempty_line(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    for line in text.splitlines():
        if line.strip() != "":
            return line.rstrip("\r\n")
    return None


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    pref_text = _read_text(workspace / "input" / "preferences.yaml")
    lib_rows = _load_csv_dicts(workspace / "input" / "library.csv")
    quote_text = _read_text(workspace / "input" / "dmx_quotes.txt")
    if pref_text is None or lib_rows is None or quote_text is None:
        return None
    prefs = _parse_simple_yaml_map(pref_text)
    if prefs is None:
        return None
    try:
        lm = prefs["listening_mode"]
        mode_name = lm["name"]
        env_vars = lm["env"]
        alias_name = lm["alias"]["name"]
        alias_message = lm["alias"]["message"]
        if not isinstance(env_vars, dict):
            return None
    except Exception:
        return None
    banner_line = _get_first_nonempty_line(quote_text)
    if banner_line is None:
        return None
    total_tracks = len(lib_rows)
    dmx_rows = [r for r in lib_rows if r.get("artist") == "DMX"]
    dmx_tracks = len(dmx_rows)
    try:
        dmx_total_duration = sum(int(r["duration_seconds"]) for r in dmx_rows)
    except Exception:
        return None
    return {
        "mode_name": mode_name,
        "env_vars": env_vars,
        "alias_name": alias_name,
        "alias_message": alias_message,
        "banner": banner_line,
        "library_stats": {
            "total_tracks": total_tracks,
            "dmx_tracks": dmx_tracks,
            "dmx_total_duration_seconds": dmx_total_duration,
        },
    }


def _posix_env_set(script: str, key: str, value: str) -> bool:
    q_val_double = f"\"{re.escape(value)}\""
    q_val_single = f"'{re.escape(value)}'"
    q_val_plain = re.escape(value)
    alt_val = f"(?:{q_val_double}|{q_val_single}|{q_val_plain})"
    pattern_export_inline = rf"(?m)^\s*export\s+{re.escape(key)}\s*=\s*{alt_val}(\s|;|$)"
    if re.search(pattern_export_inline, script):
        return True
    pattern_assign = rf"(?m)^\s*{re.escape(key)}\s*=\s*{alt_val}(\s|;|$)"
    pattern_export = rf"(?m)^\s*export\s+{re.escape(key)}(\s|;|$)"
    return bool(re.search(pattern_assign, script) and re.search(pattern_export, script))


def _posix_alias_defined(script: str, alias_name: str, message: str) -> bool:
    m = re.search(rf"(?m)^\s*alias\s+{re.escape(alias_name)}\s*=\s*(.+)$", script)
    if not m:
        return False
    alias_line = m.group(0)
    return message in alias_line


def _posix_idempotent_hint(script: str, alias_name: str) -> bool:
    if re.search(rf"(?m)^\s*unalias\s+-f?\s*{re.escape(alias_name)}(\s|;|$)", script):
        return True
    if re.search(r'(?m)^\s*if\s+\[.*\];\s*then', script) and "alias" in script:
        return True
    return False


def _posix_unset_env(script: str, key: str) -> bool:
    return bool(re.search(rf"(?m)^\s*unset(\s+-v)?\s+{re.escape(key)}(\s|;|$)", script))


def _posix_unalias(script: str, alias_name: str) -> bool:
    return bool(re.search(rf"(?m)^\s*unalias\s+-f?\s*{re.escape(alias_name)}(\s|;|$)", script))


def _ps_env_set(script: str, key: str, value: str) -> bool:
    return bool(re.search(rf"(?im)^\s*\$Env:{re.escape(key)}\s*=\s*(['\"])({re.escape(value)})\1\s*$", script))


def _ps_command_defined(script: str, name: str, message: str) -> bool:
    has_func = bool(re.search(rf"(?im)^\s*function\s+{re.escape(name)}\b", script))
    has_alias = bool(re.search(rf"(?im)^\s*Set-Alias\s+{re.escape(name)}\b", script))
    has_message = message in script
    return (has_func or has_alias) and has_message


def _ps_idempotent_hint(script: str, name: str) -> bool:
    if re.search(rf"(?im)Remove-Item\s+(function|alias):{re.escape(name)}\b", script):
        return True
    if re.search(rf"(?im)Set-Alias\s+{re.escape(name)}\b.*-Force\b", script):
        return True
    if re.search(rf"(?im)^\s*if\s*\(", script) and name in script:
        return True
    return False


def _ps_env_cleared(script: str, key: str) -> bool:
    pat_null = rf"(?im)^\s*\$Env:{re.escape(key)}\s*=\s*\$null\s*$"
    pat_remove_env_back = rf"(?im)^\s*Remove-Item\s+Env:\\{re.escape(key)}(\s|;|$)"
    pat_remove_env_colon = rf"(?im)^\s*Remove-Item\s+Env:{re.escape(key)}(\s|;|$)"
    return bool(re.search(pat_null, script) or re.search(pat_remove_env_back, script) or re.search(pat_remove_env_colon, script))


def _ps_command_removed(script: str, name: str) -> bool:
    return bool(re.search(rf"(?im)Remove-Item\s+(function|alias):{re.escape(name)}\b", script))


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _status_contains_activation(text: str) -> bool:
    posix_ok = bool(re.search(r"(?m)\b(source|\.)\s+(\./)?output/enable_listening_mode\.sh\b", text))
    ps_ok = bool(re.search(r"(?im)^\s*\.\s+(\.\\|\.\/)?output[\\/]+Enable-ListeningMode\.ps1\b", text))
    return posix_ok and ps_ok


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "output_enable_sh_exists": 0.0,
        "output_enable_sh_env_vars_set": 0.0,
        "output_enable_sh_alias_defined": 0.0,
        "output_enable_sh_idempotent": 0.0,
        "output_disable_sh_exists": 0.0,
        "output_disable_sh_env_vars_unset": 0.0,
        "output_disable_sh_alias_removed": 0.0,
        "output_enable_ps1_exists": 0.0,
        "output_enable_ps1_env_vars_set": 0.0,
        "output_enable_ps1_command_defined": 0.0,
        "output_enable_ps1_idempotent": 0.0,
        "output_disable_ps1_exists": 0.0,
        "output_disable_ps1_env_vars_cleared": 0.0,
        "output_disable_ps1_command_removed": 0.0,
        "output_session_profile_exists": 0.0,
        "output_session_profile_fields_exact": 0.0,
        "output_session_profile_values_correct": 0.0,
        "output_status_md_exists": 0.0,
        "output_status_md_mode_and_banner": 0.0,
        "output_status_md_counts_present": 0.0,
        "output_status_md_activation_instructions": 0.0,
    }

    expected = _compute_expected(workspace)

    sh_enable = workspace / "output" / "enable_listening_mode.sh"
    sh_disable = workspace / "output" / "disable_listening_mode.sh"
    ps_enable = workspace / "output" / "Enable-ListeningMode.ps1"
    ps_disable = workspace / "output" / "Disable-ListeningMode.ps1"
    profile_json_path = workspace / "output" / "session_profile.json"
    status_md_path = workspace / "output" / "STATUS.md"

    sh_enable_text = _read_text(sh_enable)
    if sh_enable_text is not None:
        scores["output_enable_sh_exists"] = 1.0
        if expected is not None:
            env_ok = True
            for k, v in expected["env_vars"].items():
                if not _posix_env_set(sh_enable_text, k, v):
                    env_ok = False
                    break
            scores["output_enable_sh_env_vars_set"] = 1.0 if env_ok else 0.0
            scores["output_enable_sh_alias_defined"] = 1.0 if _posix_alias_defined(
                sh_enable_text, expected["alias_name"], expected["alias_message"]
            ) else 0.0
            scores["output_enable_sh_idempotent"] = 1.0 if _posix_idempotent_hint(
                sh_enable_text, expected["alias_name"]
            ) else 0.0

    sh_disable_text = _read_text(sh_disable)
    if sh_disable_text is not None:
        scores["output_disable_sh_exists"] = 1.0
        if expected is not None:
            unset_ok = True
            for k in expected["env_vars"].keys():
                if not _posix_unset_env(sh_disable_text, k):
                    unset_ok = False
                    break
            scores["output_disable_sh_env_vars_unset"] = 1.0 if unset_ok else 0.0
            scores["output_disable_sh_alias_removed"] = 1.0 if _posix_unalias(
                sh_disable_text, expected["alias_name"]
            ) else 0.0

    ps_enable_text = _read_text(ps_enable)
    if ps_enable_text is not None:
        scores["output_enable_ps1_exists"] = 1.0
        if expected is not None:
            env_ps_ok = True
            for k, v in expected["env_vars"].items():
                if not _ps_env_set(ps_enable_text, k, v):
                    env_ps_ok = False
                    break
            scores["output_enable_ps1_env_vars_set"] = 1.0 if env_ps_ok else 0.0
            scores["output_enable_ps1_command_defined"] = 1.0 if _ps_command_defined(
                ps_enable_text, expected["alias_name"], expected["alias_message"]
            ) else 0.0
            scores["output_enable_ps1_idempotent"] = 1.0 if _ps_idempotent_hint(
                ps_enable_text, expected["alias_name"]
            ) else 0.0

    ps_disable_text = _read_text(ps_disable)
    if ps_disable_text is not None:
        scores["output_disable_ps1_exists"] = 1.0
        if expected is not None:
            env_clear_ok = True
            for k in expected["env_vars"].keys():
                if not _ps_env_cleared(ps_disable_text, k):
                    env_clear_ok = False
                    break
            scores["output_disable_ps1_env_vars_cleared"] = 1.0 if env_clear_ok else 0.0
            scores["output_disable_ps1_command_removed"] = 1.0 if _ps_command_removed(
                ps_disable_text, expected["alias_name"]
            ) else 0.0

    profile_json_obj = _load_json(profile_json_path)
    if profile_json_obj is not None:
        scores["output_session_profile_exists"] = 1.0
        if expected is not None and isinstance(profile_json_obj, dict):
            expected_top_keys = {"mode_name", "env_vars", "alias", "banner", "library_stats"}
            struct_ok = set(profile_json_obj.keys()) == expected_top_keys
            if struct_ok:
                alias_obj = profile_json_obj.get("alias")
                lib_stats_obj = profile_json_obj.get("library_stats")
                struct_ok = (
                    isinstance(profile_json_obj.get("env_vars"), dict)
                    and isinstance(alias_obj, dict)
                    and set(alias_obj.keys()) == {"name", "message"}
                    and isinstance(lib_stats_obj, dict)
                    and set(lib_stats_obj.keys()) == {
                        "total_tracks",
                        "dmx_tracks",
                        "dmx_total_duration_seconds",
                    }
                )
            scores["output_session_profile_fields_exact"] = 1.0 if struct_ok else 0.0

            values_ok = False
            if struct_ok:
                try:
                    values_ok = (
                        profile_json_obj["mode_name"] == expected["mode_name"]
                        and profile_json_obj["env_vars"] == expected["env_vars"]
                        and profile_json_obj["alias"]["name"] == expected["alias_name"]
                        and profile_json_obj["alias"]["message"] == expected["alias_message"]
                        and profile_json_obj["banner"] == expected["banner"]
                        and profile_json_obj["library_stats"]["total_tracks"] == expected["library_stats"]["total_tracks"]
                        and profile_json_obj["library_stats"]["dmx_tracks"] == expected["library_stats"]["dmx_tracks"]
                        and profile_json_obj["library_stats"]["dmx_total_duration_seconds"]
                        == expected["library_stats"]["dmx_total_duration_seconds"]
                    )
                except Exception:
                    values_ok = False
            scores["output_session_profile_values_correct"] = 1.0 if values_ok else 0.0

    status_md_text = _read_text(status_md_path)
    if status_md_text is not None:
        scores["output_status_md_exists"] = 1.0
        if expected is not None:
            mode_banner_ok = (expected["mode_name"] in status_md_text) and (expected["banner"] in status_md_text)
            scores["output_status_md_mode_and_banner"] = 1.0 if mode_banner_ok else 0.0
            counts_ok = all(
                re.search(rf"(?m)\b{re.escape(str(n))}\b", status_md_text) is not None
                for n in [
                    expected["library_stats"]["total_tracks"],
                    expected["library_stats"]["dmx_tracks"],
                    expected["library_stats"]["dmx_total_duration_seconds"],
                ]
            )
            scores["output_status_md_counts_present"] = 1.0 if counts_ok else 0.0
            scores["output_status_md_activation_instructions"] = 1.0 if _status_contains_activation(
                status_md_text
            ) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()