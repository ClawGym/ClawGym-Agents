import json
import re
import subprocess
import sys
from pathlib import Path


EXPECTED_RUN_CHECKS_PY = """#!/usr/bin/env python3
import json
import os
import re
import sys

def main():
    config_path = os.path.join("config", "checks.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"CONFIG ERROR: Missing {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"CONFIG ERROR: JSON parse error at line {e.lineno} col {e.colno}: {e.msg}")
        sys.exit(1)

    errors = []

    # python_version must be a string like '3.10'
    if "python_version" not in data:
        errors.append("Missing key 'python_version' (e.g., '3.10').")
    else:
        pv = data["python_version"]
        if not isinstance(pv, str) or re.fullmatch(r"\\d+\\.\\d+", pv) is None:
            errors.append(
                f"Invalid value for python_version: expected string like '3.10', got {type(pv).__name__}={pv!r}."
            )

    # formatting.line_length must be an int between 60 and 120
    if not isinstance(data.get("formatting"), dict):
        errors.append("Missing object 'formatting' with key 'line_length' (int 60-120).")
    else:
        fmt = data["formatting"]
        if "line_length" not in fmt:
            errors.append("Missing key 'formatting.line_length' (int 60-120).")
        else:
            ll = fmt["line_length"]
            if not isinstance(ll, int):
                errors.append(
                    f"Invalid type for formatting.line_length: expected int, got {type(ll).__name__}."
                )
            elif not (60 <= ll <= 120):
                errors.append(
                    f"Invalid value for formatting.line_length: {ll} (must be between 60 and 120)."
                )

    # tests.enabled (bool) and tests.min_coverage (int 0-100)
    if not isinstance(data.get("tests"), dict):
        errors.append(
            "Missing object 'tests' with keys 'enabled' (bool) and 'min_coverage' (int 0-100)."
        )
    else:
        tests = data["tests"]
        if "enabled" not in tests:
            errors.append("Missing key 'tests.enabled' (bool).")
        else:
            en = tests["enabled"]
            if not isinstance(en, bool):
                errors.append(
                    f"Invalid type for tests.enabled: expected bool, got {type(en).__name__}."
                )
        if "min_coverage" not in tests:
            errors.append("Missing key 'tests.min_coverage' (int 0-100).")
        else:
            mc = tests["min_coverage"]
            if not isinstance(mc, int):
                errors.append(
                    f"Invalid type for tests.min_coverage: expected int, got {type(mc).__name__}."
                )
            elif not (0 <= mc <= 100):
                errors.append(
                    f"Invalid value for tests.min_coverage: {mc} (must be 0-100)."
                )

    if errors:
        print("CONFIG ERRORS:")
        for e in errors:
            print(f"- {e}")
        print("Fix the issues in config/checks.json and re-run this script.")
        sys.exit(1)

    print("All checks passed.")
    print(f"python_version={data['python_version']}")
    print(f"formatting.line_length={data['formatting']['line_length']}")
    print(f"tests.enabled={data['tests']['enabled']}")
    print(f"tests.min_coverage={data['tests']['min_coverage']}")
    sys.exit(0)

if __name__ == "__main__":
    main()
"""


def read_text_safe(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return text, None
    except FileNotFoundError:
        return None, f"missing:{path}"
    except Exception as e:
        return None, f"error:{e}"


def load_json_safe(path: Path):
    text, err = read_text_safe(path)
    if err or text is None:
        return None, f"read_error:{err or 'unknown'}"
    try:
        data = json.loads(text)
        return data, None
    except json.JSONDecodeError as e:
        return None, f"json_error:line {e.lineno} col {e.colno} {e.msg}"


def normalize_newlines(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    while s.endswith("\n"):
        s = s[:-1]
    return s


def run_check_command(workspace: Path):
    cmd = [sys.executable, "tools/run_checks.py"]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
        return res.returncode, res.stdout
    except Exception as e:
        return None, f"run_error:{e}"


def validate_config_manual(data):
    issues = []
    normalized = {}
    # python_version
    if "python_version" not in data:
        issues.append("missing:python_version")
    else:
        pv = data.get("python_version")
        if not isinstance(pv, str):
            issues.append("type:python_version")
        elif re.fullmatch(r"\d+\.\d+", pv) is None:
            issues.append("pattern:python_version")
        else:
            normalized["python_version"] = pv
    # formatting.line_length
    fmt = data.get("formatting")
    if not isinstance(fmt, dict):
        issues.append("missing:formatting")
    else:
        if "line_length" not in fmt:
            issues.append("missing:formatting.line_length")
        else:
            ll = fmt.get("line_length")
            if not isinstance(ll, int):
                issues.append("type:formatting.line_length")
            elif not (60 <= ll <= 120):
                issues.append("range:formatting.line_length")
            else:
                normalized["formatting.line_length"] = ll
    # tests.enabled and tests.min_coverage
    tests = data.get("tests")
    if not isinstance(tests, dict):
        issues.append("missing:tests")
    else:
        if "enabled" not in tests:
            issues.append("missing:tests.enabled")
        else:
            en = tests.get("enabled")
            if not isinstance(en, bool):
                issues.append("type:tests.enabled")
            else:
                normalized["tests.enabled"] = en
        if "min_coverage" not in tests:
            issues.append("missing:tests.min_coverage")
        else:
            mc = tests.get("min_coverage")
            if not isinstance(mc, int):
                issues.append("type:tests.min_coverage")
            elif not (0 <= mc <= 100):
                issues.append("range:tests.min_coverage")
            else:
                normalized["tests.min_coverage"] = mc
    return len(issues) == 0, issues, normalized


def parse_sections(text: str, labels):
    lines = text.splitlines()
    positions = []
    contents = {label: "" for label in labels}
    current = None
    for idx, line in enumerate(lines):
        matched_label = None
        rest_after_colon = None
        for label in labels:
            prefix = f"{label}:"
            if line.startswith(prefix):
                matched_label = label
                rest_after_colon = line[len(prefix):].lstrip()
                break
        if matched_label is not None:
            current = matched_label
            positions.append((matched_label, idx))
            if rest_after_colon:
                contents[current] = rest_after_colon
            else:
                contents[current] = ""
            continue
        if current is not None:
            if contents[current]:
                contents[current] += "\n" + line
            else:
                contents[current] = line
    return contents, positions


def count_sentences(text: str) -> int:
    if not text:
        return 0
    s = " ".join(text.strip().split())
    matches = re.findall(r"[.!?](?:\s|$)", s)
    return len(matches)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_passes_tool_run": 0.0,
        "checks_after_captured_exactly": 0.0,
        "checks_after_includes_success_line": 0.0,
        "checker_script_unchanged_on_success": 0.0,
        "config_manual_valid": 0.0,
        "email_sections_order_and_subject": 0.0,
        "email_summary_1_to_3_sentences": 0.0,
        "email_root_cause_grounded": 0.0,
        "email_changes_bullets_cover_corrected_values": 0.0,
        "email_how_to_run_exact_command": 0.0,
        "email_ps_quote_verbatim": 0.0,
    }

    # Manual validation of config file
    config_path = workspace / "config" / "checks.json"
    config_data, cfg_err = load_json_safe(config_path)
    normalized_cfg = {}
    if cfg_err is None and isinstance(config_data, dict):
        valid_manual, _, normalized_cfg = validate_config_manual(config_data)
        if valid_manual:
            scores["config_manual_valid"] = 1.0
        else:
            scores["config_manual_valid"] = 0.0
    else:
        scores["config_manual_valid"] = 0.0

    # Run the check command
    rc, out = run_check_command(workspace)
    run_ok = False
    expected_stdout = ""
    if isinstance(rc, int) and isinstance(out, str):
        expected_stdout = out
        if rc == 0 and "All checks passed." in out:
            run_ok = True
    scores["config_passes_tool_run"] = 1.0 if run_ok else 0.0

    # Verify checks_after.txt captured stdout exactly and includes success line
    checks_after_path = workspace / "output" / "checks_after.txt"
    after_text, after_err = read_text_safe(checks_after_path)
    if run_ok and after_err is None and after_text is not None:
        if normalize_newlines(after_text) == normalize_newlines(expected_stdout):
            scores["checks_after_captured_exactly"] = 1.0
        if "All checks passed." in after_text:
            scores["checks_after_includes_success_line"] = 1.0

    # Verify checker script unchanged only if run succeeded
    if run_ok:
        run_checks_path = workspace / "tools" / "run_checks.py"
        run_checks_text, rc_err = read_text_safe(run_checks_path)
        if rc_err is None and run_checks_text is not None:
            if normalize_newlines(run_checks_text) == normalize_newlines(EXPECTED_RUN_CHECKS_PY):
                scores["checker_script_unchanged_on_success"] = 1.0

    # Validate email content and structure
    email_path = workspace / "output" / "email_to_team.txt"
    email_text, email_err = read_text_safe(email_path)
    labels = ["Subject", "Summary", "Root cause", "Changes made", "How to run locally", "P.S."]
    if email_err is None and email_text is not None:
        email_contents, positions = parse_sections(email_text, labels)
        # Order and presence check
        encountered = [lbl for (lbl, _) in positions if lbl in labels]
        order_ok = encountered == labels and all(lbl in encountered for lbl in labels)
        # Subject exact
        subject_content = email_contents.get("Subject", "")
        first_line = ""
        for ln in subject_content.splitlines() if subject_content else [""]:
            if ln.strip():
                first_line = ln.strip()
                break
        if not first_line:
            first_line = subject_content.strip()
        subject_ok = first_line == "Fix: Team dev checks config"
        if order_ok and subject_ok:
            scores["email_sections_order_and_subject"] = 1.0

        # Summary 1-3 sentences
        summary_text = email_contents.get("Summary", "").strip()
        if summary_text:
            num_sent = count_sentences(summary_text)
            if 1 <= num_sent <= 3:
                scores["email_summary_1_to_3_sentences"] = 1.0

        # Root cause grounded in initial error messages
        root_text = email_contents.get("Root cause", "")
        root_lc = root_text.lower()
        key_tokens = [
            "python_version",
            "formatting.line_length",
            "line_length",
            "tests.enabled",
            "tests.min_coverage",
            "tests",
            "formatting",
        ]
        error_tokens = [
            "missing key",
            "invalid type",
            "invalid value",
            "missing object",
            "json parse error",
            "config error",
            "config errors",
        ]
        has_key_token = any(tok in root_lc for tok in key_tokens)
        has_error_token = any(tok in root_lc for tok in error_tokens)
        if root_text.strip() and has_key_token and has_error_token:
            scores["email_root_cause_grounded"] = 1.0

        # Changes made bullets cover corrected keys and values
        changes_text = email_contents.get("Changes made", "")
        bullet_lines = []
        for ln in changes_text.splitlines():
            ls = ln.lstrip()
            if ls.startswith("- ") or ls.startswith("* "):
                bullet_lines.append(ls[2:].strip())
        changes_ok = False
        if bullet_lines and normalized_cfg:
            exp = {
                "python_version": str(normalized_cfg.get("python_version", "")),
                "formatting.line_length": str(normalized_cfg.get("formatting.line_length", "")),
                "tests.enabled": (
                    "true" if normalized_cfg.get("tests.enabled", None) is True
                    else ("false" if normalized_cfg.get("tests.enabled", None) is False else "")
                ),
                "tests.min_coverage": str(normalized_cfg.get("tests.min_coverage", "")),
            }

            def has_bullet_for(key_synonyms, expected_value, value_is_bool=False):
                for b in bullet_lines:
                    b_lc = b.lower()
                    if any(ks in b_lc for ks in key_synonyms):
                        if value_is_bool:
                            if expected_value and expected_value.lower() in b_lc:
                                return True
                        else:
                            if expected_value and expected_value in b:
                                return True
                return False

            ok_python = has_bullet_for(["python_version"], exp["python_version"])
            ok_line_length = has_bullet_for(["formatting.line_length", "line_length"], exp["formatting.line_length"])
            ok_tests_enabled = has_bullet_for(["tests.enabled", "enabled"], exp["tests.enabled"], value_is_bool=True)
            ok_min_cov = has_bullet_for(["tests.min_coverage", "min_coverage"], exp["tests.min_coverage"])
            changes_ok = ok_python and ok_line_length and ok_tests_enabled and ok_min_cov
        if changes_ok:
            scores["email_changes_bullets_cover_corrected_values"] = 1.0

        # How to run locally exact command included
        how_text = email_contents.get("How to run locally", "")
        if "python tools/run_checks.py" in how_text:
            scores["email_how_to_run_exact_command"] = 1.0

        # P.S. includes exact uplift quote
        uplift_path = workspace / "uplift" / "uplift.txt"
        uplift_text, up_err = read_text_safe(uplift_path)
        ps_text = email_contents.get("P.S.", "")
        if up_err is None and uplift_text is not None:
            uplift_line = normalize_newlines(uplift_text).split("\n")[0]
            for ln in ps_text.splitlines():
                if ln.strip() == uplift_line:
                    scores["email_ps_quote_verbatim"] = 1.0
                    break

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()