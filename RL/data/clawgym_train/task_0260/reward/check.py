import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(errors="ignore")
        except Exception:
            return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(str(path), os.X_OK)
    except Exception:
        return False


def _semver_tuple(ver: str) -> Optional[Tuple[int, int, int]]:
    """
    Parse strict semantic version 'X.Y.Z' into a tuple of ints.
    Returns None if not strictly matching three numeric components.
    """
    if not isinstance(ver, str):
        return None
    m = re.fullmatch(r"\s*(\d+)\.(\d+)\.(\d+)\s*", ver)
    if not m:
        return None
    try:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return None


def _ascii_printable(s: str) -> bool:
    # Allow tabs and newlines; but keep to basic ASCII to avoid emojis.
    for ch in s:
        o = ord(ch)
        if ch in ("\n", "\r", "\t"):
            continue
        if o < 32 or o > 126:
            return False
    return True


def _first_line(s: str) -> str:
    if not s:
        return ""
    return s.splitlines()[0] if s.splitlines() else s


def _split_status_names(line: str) -> List[str]:
    # Split by commas, strip whitespace, drop empty
    return [tok.strip() for tok in line.split(",") if tok.strip()]


def _strip_prefixes_for_path(line: str) -> str:
    # Remove common prefixes like "PATH used:" or "PATH=" to get the path string
    l = line.strip()
    prefixes = ["PATH used:", "PATH=", "Path used:", "path used:", "Used PATH:", "USED PATH:"]
    for p in prefixes:
        if l.startswith(p):
            return l[len(p):].strip()
    return l


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_exists_executable": 0.0,
        "validation_json_structure_and_order": 0.0,
        "validation_json_semantic_logic": 0.0,
        "validation_log_path_contains_tools_bin": 0.0,
        "validation_log_tools_bin_is_first": 0.0,
        "validation_log_mentions_io_and_exit": 0.0,
        "validation_log_contains_chosen_commands": 0.0,
        "status_txt_length_and_lines": 0.0,
        "status_txt_matches_failures": 0.0,
        "login_banner_constraints": 0.0,
        "tools_bin_dir_exists": 0.0,
    }

    # Paths
    script_path = workspace / "scripts" / "check_tools.sh"
    req_path = workspace / "input" / "requirements.json"
    banner_in_path = workspace / "input" / "login_banner.txt"
    validation_log_path = workspace / "outputs" / "validation.log"
    validation_json_path = workspace / "outputs" / "validation.json"
    status_txt_path = workspace / "outputs" / "status.txt"
    banner_out_path = workspace / "outputs" / "login_banner.txt"
    tools_bin_path = workspace / "tools" / "bin"

    # Check script existence and executable
    if _is_executable_file(script_path):
        scores["script_exists_executable"] = 1.0

    # Tools bin dir existence (should exist if script created or user created)
    try:
        if tools_bin_path.exists() and tools_bin_path.is_dir():
            scores["tools_bin_dir_exists"] = 1.0
    except Exception:
        pass

    # Load requirements
    req = _load_json(req_path)
    tools_spec: List[Dict[str, Any]] = []
    if isinstance(req, dict) and isinstance(req.get("tools"), list):
        tools_spec = []
        ok = True
        for t in req["tools"]:
            if not isinstance(t, dict):
                ok = False
                break
            name = t.get("name")
            min_version = t.get("min_version")
            commands = t.get("commands")
            if not (isinstance(name, str) and isinstance(min_version, str) and isinstance(commands, list) and all(isinstance(c, str) for c in commands)):
                ok = False
                break
            tools_spec.append({"name": name, "min_version": min_version, "commands": commands})
        if not ok:
            tools_spec = []
    else:
        tools_spec = []

    # Load validation.json
    val_json = _load_json(validation_json_path)

    # Validate structure and order of validation.json
    structure_ok = False
    semantic_ok = False
    failing_tools_from_json: List[str] = []

    if tools_spec and isinstance(val_json, list):
        # Check basic structure
        if len(val_json) == len(tools_spec) and all(isinstance(obj, dict) for obj in val_json):
            all_fields_ok = True
            all_req_ok = True
            semantic_all_ok = True
            for idx, (spec, obj) in enumerate(zip(tools_spec, val_json)):
                # Required fields presence and types
                tool_name = obj.get("tool")
                chosen_command = obj.get("chosen_command", None)
                found_version = obj.get("found_version", None)
                requirement = obj.get("requirement")
                meets_requirement = obj.get("meets_requirement")
                error = obj.get("error", None)

                # Order and tool field
                if tool_name != spec["name"]:
                    all_req_ok = False

                # requirement must equal ">=<min_version>"
                expected_req = f">={spec['min_version']}"
                if requirement != expected_req:
                    all_req_ok = False

                # chosen_command must be None or string
                if not (chosen_command is None or isinstance(chosen_command, str)):
                    all_fields_ok = False

                # If chosen_command is str, must be one of commands
                if isinstance(chosen_command, str) and chosen_command not in spec["commands"]:
                    all_fields_ok = False

                # found_version must be None or strict semver
                if found_version is not None:
                    if not isinstance(found_version, str):
                        all_fields_ok = False
                    else:
                        if _semver_tuple(found_version) is None:
                            # Found version should be semantic version only as per spec
                            all_fields_ok = False

                # meets_requirement must be boolean
                if not isinstance(meets_requirement, bool):
                    all_fields_ok = False

                # error must be None or str
                if not (error is None or isinstance(error, str)):
                    all_fields_ok = False

            structure_ok = all_fields_ok and all_req_ok

            # Semantic checks: version comparison and internal consistency
            if structure_ok:
                for spec, obj in zip(tools_spec, val_json):
                    chosen_command = obj.get("chosen_command", None)
                    found_version = obj.get("found_version", None)
                    meets_requirement = obj.get("meets_requirement")
                    error = obj.get("error", None)

                    min_tuple = _semver_tuple(spec["min_version"])
                    found_tuple = _semver_tuple(found_version) if isinstance(found_version, str) else None

                    # Compute expected meets requirement
                    expected_meets = False
                    if found_tuple is not None and min_tuple is not None:
                        expected_meets = found_tuple >= min_tuple

                    # If chosen_command is None or found_version is None or unparsable -> must be False
                    if chosen_command is None or found_tuple is None:
                        if meets_requirement:
                            semantic_all_ok = False
                    else:
                        # If found and chosen exist, meets must match computed
                        if meets_requirement != expected_meets:
                            semantic_all_ok = False

                    # Error expectations
                    if meets_requirement:
                        # When passing, error should be None and both chosen and found present
                        if error not in (None, ""):
                            semantic_all_ok = False
                        if not (isinstance(chosen_command, str) and isinstance(found_version, str)):
                            semantic_all_ok = False
                    else:
                        # When failing, error should be a non-empty string (per spec says record the error message)
                        if not (isinstance(error, str) and error.strip() != ""):
                            semantic_all_ok = False

                    # Track failing tools by meets flag
                    if not meets_requirement:
                        failing_tools_from_json.append(obj.get("tool"))

                semantic_ok = semantic_all_ok

    scores["validation_json_structure_and_order"] = 1.0 if structure_ok else 0.0
    scores["validation_json_semantic_logic"] = 1.0 if semantic_ok else 0.0

    # Validate status.txt
    status_text = _read_text(status_txt_path) or ""
    if status_text:
        total_len = len(status_text.strip())
        lines = status_text.strip("\n").splitlines()
        # length and line count constraints
        if total_len <= 150 and 1 <= len(lines) <= 2 and _ascii_printable(status_text):
            scores["status_txt_length_and_lines"] = 1.0
        else:
            scores["status_txt_length_and_lines"] = 0.0

        status_match_ok = False
        if structure_ok:
            if len(failing_tools_from_json) == 0:
                # Should not list tool names; keep it succinct. We check only that it doesn't contain any tool name.
                contains_tool_name = False
                lower = status_text.lower()
                for spec in tools_spec:
                    name = spec["name"].lower()
                    if name in lower:
                        contains_tool_name = True
                        break
                if not contains_tool_name and total_len <= 150 and 1 <= len(lines) <= 2:
                    status_match_ok = True
            else:
                # Must be a single short line listing only the failing tool names, comma-separated
                if len(lines) == 1:
                    # Allow optional spaces around commas; ensure only the failing names appear and in the same order
                    tokens = _split_status_names(lines[0])
                    if tokens == failing_tools_from_json:
                        # Ensure the line contains only names and commas/spaces
                        # Reconstruct acceptable line variants and compare stripped non-alnum characters.
                        # Here we enforce exact list adherence by re-joining with commas with optional spaces:
                        # Accept either "a,b,c" or "a, b, c"
                        variant1 = ",".join(failing_tools_from_json)
                        variant2 = ", ".join(failing_tools_from_json)
                        if lines[0].strip() in (variant1, variant2):
                            status_match_ok = True

        scores["status_txt_matches_failures"] = 1.0 if status_match_ok else 0.0
    else:
        scores["status_txt_length_and_lines"] = 0.0
        scores["status_txt_matches_failures"] = 0.0

    # Validate validation.log
    log_text = _read_text(validation_log_path) or ""
    if log_text:
        first = _first_line(log_text)
        expected_tools_bin = str((tools_bin_path).resolve())
        # Check that first line mentions the tools/bin path
        contains_ok = expected_tools_bin in first
        scores["validation_log_path_contains_tools_bin"] = 1.0 if contains_ok else 0.0

        # Check that tools/bin is the first component in the PATH line if we can parse it
        # Remove common prefixes and then split by colon to find first element
        first_processed = _strip_prefixes_for_path(first)
        # split by ':' to simulate PATH
        components = [c for c in first_processed.split(":") if c != ""]
        is_first = False
        if components:
            # Accept exact match of first component with expected_tools_bin
            if components[0] == expected_tools_bin:
                is_first = True
        scores["validation_log_tools_bin_is_first"] = 1.0 if is_first else 0.0

        lower_log = log_text.lower()
        io_ok = ("stdout" in lower_log) and ("stderr" in lower_log) and ("exit code" in lower_log or "exit_code" in lower_log or "exitcode" in lower_log)
        scores["validation_log_mentions_io_and_exit"] = 1.0 if io_ok else 0.0

        # For each chosen_command in validation.json, ensure the log mentions it
        chosen_ok = False
        if isinstance(val_json, list) and structure_ok:
            all_found = True
            for obj in val_json:
                cc = obj.get("chosen_command")
                if isinstance(cc, str):
                    if cc not in log_text:
                        all_found = False
                        break
            chosen_ok = all_found
        scores["validation_log_contains_chosen_commands"] = 1.0 if chosen_ok else 0.0
    else:
        scores["validation_log_path_contains_tools_bin"] = 0.0
        scores["validation_log_tools_bin_is_first"] = 0.0
        scores["validation_log_mentions_io_and_exit"] = 0.0
        scores["validation_log_contains_chosen_commands"] = 0.0

    # Validate outputs/login_banner.txt
    banner_out_text = _read_text(banner_out_path) or ""
    banner_constraints_ok = False
    if banner_out_text:
        trimmed = banner_out_text.strip()
        length_ok = len(trimmed) <= 120 and len(trimmed) > 0
        emoji_ok = _ascii_printable(trimmed)
        # Count sentence enders ., !, ?
        enders = re.findall(r"[.!?]", trimmed)
        sentence_ok = len(enders) <= 1
        # No more than one sentence and minimal lines (ideally one line)
        lines_count = len(trimmed.splitlines())
        lines_ok = lines_count <= 2  # tolerate a trailing newline
        banner_constraints_ok = length_ok and emoji_ok and sentence_ok and lines_ok
    scores["login_banner_constraints"] = 1.0 if banner_constraints_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()