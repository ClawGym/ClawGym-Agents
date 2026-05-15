import json
import re
import sys
import subprocess
from pathlib import Path


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _format_value_variants(value):
    if isinstance(value, bool):
        return {"true", "True"} if value else {"false", "False"}
    if value is None:
        return {"null"}
    if isinstance(value, (int, float)):
        return {str(value)}
    if isinstance(value, str):
        return {value}
    try:
        return {json.dumps(value, separators=(",", ":"))}
    except Exception:
        return {str(value)}


def _compute_expected_state(mock: dict, desired: dict) -> dict:
    expected = dict(mock) if isinstance(mock, dict) else {}
    for k, v in (desired.items() if isinstance(desired, dict) else []):
        expected[k] = v
    return expected


def _read_log_lines(log_path: Path):
    try:
        with log_path.open("r", encoding="utf-8") as f:
            return [line.rstrip("\n").rstrip("\r") for line in f.read().splitlines()]
    except Exception:
        return None


def _match_changed_line(key: str, old_val, new_val, actual: str) -> bool:
    old_variants = _format_value_variants(old_val)
    new_variants = _format_value_variants(new_val)
    candidates = {f"changed key {key}: {o} -> {n}" for o in old_variants for n in new_variants}
    return actual in candidates


def _match_added_line(key: str, new_val, actual: str) -> bool:
    new_variants = _format_value_variants(new_val)
    candidates = {f"added key {key}: {n}" for n in new_variants}
    return actual in candidates


def _match_unchanged_line(key: str, val, actual: str) -> bool:
    variants = _format_value_variants(val)
    candidates = {f"unchanged key {key}: {v}" for v in variants}
    return actual in candidates


def _grade_applied_state(workspace: Path, desired: dict, mock: dict) -> float:
    out_state_path = workspace / "output" / "applied_os_state.json"
    applied = _safe_load_json(out_state_path)
    if applied is None or not isinstance(desired, dict) or not isinstance(mock, dict):
        return 0.0
    expected = _compute_expected_state(mock, desired)
    if not isinstance(applied, dict):
        return 0.0
    exp_keys = set(expected.keys())
    app_keys = set(applied.keys())
    if exp_keys != app_keys:
        return 0.0
    for k in exp_keys:
        if applied.get(k) != expected.get(k):
            return 0.0
    return 1.0


def _grade_apply_log(workspace: Path, desired: dict, mock: dict) -> float:
    log_path = workspace / "output" / "apply.log"
    lines = _read_log_lines(log_path)
    if lines is None or not isinstance(desired, dict) or not isinstance(mock, dict):
        return 0.0

    desired_items = list(desired.items())
    if len(lines) != len(desired_items):
        return 0.0

    for idx, (key, desired_val) in enumerate(desired_items):
        actual_line = lines[idx]
        if key in mock:
            old_val = mock[key]
            if old_val == desired_val:
                if not _match_unchanged_line(key, desired_val, actual_line):
                    return 0.0
            else:
                if not _match_changed_line(key, old_val, desired_val, actual_line):
                    return 0.0
        else:
            if not _match_added_line(key, desired_val, actual_line):
                return 0.0
    return 1.0


def _run_validator(workspace: Path) -> float:
    validate_path = workspace / "tests" / "validate.py"
    if not validate_path.exists():
        return 0.0
    try:
        proc = subprocess.run(
            [sys.executable, str(validate_path)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0 and "All validations passed." in out:
            return 1.0
        return 0.0
    except Exception:
        return 0.0


def _parse_counts_from_log(lines):
    counts = {"changed": 0, "added": 0, "unchanged": 0}
    for line in lines or []:
        if line.startswith("changed key "):
            counts["changed"] += 1
        elif line.startswith("added key "):
            counts["added"] += 1
        elif line.startswith("unchanged key "):
            counts["unchanged"] += 1
    return counts


def _extract_summary_counts_line(text: str):
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if all(word in line.lower() for word in ["changed", "added", "unchanged"]) and re.search(r"\d", line):
            return line
    return None


def _parse_counts_from_summary_line(line: str):
    lower = line.lower()
    def find_count(label: str):
        m = re.search(rf"{label}\s*[:=]\s*(\d+)", lower)
        return int(m.group(1)) if m else None

    changed = find_count("changed")
    added = find_count("added")
    unchanged = find_count("unchanged")
    if changed is None or added is None or unchanged is None:
        return None
    return {"changed": changed, "added": added, "unchanged": unchanged}


def _value_present_in_line(value, line: str) -> bool:
    variants = _format_value_variants(value)
    for v in variants:
        if v in line:
            return True
    return False


def _grade_email(workspace: Path, desired: dict, mock: dict) -> float:
    email_path = workspace / "output" / "email_to_kai.txt"
    if not email_path.exists():
        return 0.0
    text = _safe_read_text(email_path)
    if not text:
        return 0.0
    lines = text.splitlines()
    if not lines:
        return 0.0

    subject_ok = lines[0].strip() == "Subject: Night Observation Mode readiness check"

    lc = text.lower()
    paragraph_ok = ("mock" in lc) and ("system" in lc) and ("star" in lc or "night" in lc)

    log_path = workspace / "output" / "apply.log"
    log_lines = _read_log_lines(log_path)
    if log_lines is None:
        return 0.0
    expected_counts = _parse_counts_from_log(log_lines)
    summary_line = _extract_summary_counts_line(text)
    if summary_line is None:
        summary_ok = False
    else:
        parsed = _parse_counts_from_summary_line(summary_line)
        summary_ok = parsed is not None and parsed == expected_counts

    applied_path = workspace / "output" / "applied_os_state.json"
    applied = _safe_load_json(applied_path)
    if not isinstance(applied, dict):
        return 0.0
    bullet_lines = [ln for ln in lines if ln.lstrip().startswith("- ")]
    bullets_ok = True
    for key, val in applied.items():
        found = False
        for bl in bullet_lines:
            if key in bl and _value_present_in_line(val, bl):
                found = True
                break
        if not found:
            bullets_ok = False
            break

    paths_ok = ("output/applied_os_state.json" in text) and ("output/apply.log" in text)

    return 1.0 if (subject_ok and paragraph_ok and summary_ok and bullets_ok and paths_ok) else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_file_exists": 0.0,
        "applied_state_correct": 0.0,
        "apply_log_order_and_format_correct": 0.0,
        "validator_passed": 0.0,
        "email_contents_valid": 0.0,
    }

    script_path = workspace / "scripts" / "apply_night_mode.py"
    if script_path.exists() and script_path.is_file():
        scores["script_file_exists"] = 1.0

    desired_path = workspace / "input" / "desired_night_settings.json"
    mock_path = workspace / "input" / "mock_os_state.json"
    desired = _safe_load_json(desired_path)
    mock = _safe_load_json(mock_path)

    scores["applied_state_correct"] = _grade_applied_state(workspace, desired, mock)
    scores["apply_log_order_and_format_correct"] = _grade_apply_log(workspace, desired, mock)
    scores["validator_passed"] = _run_validator(workspace)
    scores["email_contents_valid"] = _grade_email(workspace, desired, mock)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()