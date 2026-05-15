import json
import sys
import re
from pathlib import Path
from datetime import datetime


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(path: Path):
    try:
        return json.loads(_read_text_safe(path))
    except Exception:
        return None


def _is_iso8601_utc_z(s: str) -> bool:
    if not isinstance(s, str) or not s.endswith("Z"):
        return False
    core = s[:-1]
    try:
        # Allow fractional seconds
        datetime.fromisoformat(core)
        return True
    except Exception:
        return False


def _parse_ci_last_run(log_text: str):
    """
    Parse the last CI run segment in the aggregated log.
    Returns dict with keys: start_line_idx, complete_line_idx, steps(list of dicts{name, command, returncode}).
    If no run found, returns None.
    """
    if not log_text:
        return None
    lines = log_text.splitlines()
    # Find last start
    last_start_idx = None
    for idx, line in enumerate(lines):
        if line.startswith("== CI START "):
            last_start_idx = idx
    if last_start_idx is None:
        return None
    # Find complete after start
    complete_idx = None
    for idx in range(last_start_idx + 1, len(lines)):
        if lines[idx].startswith("== CI COMPLETE "):
            complete_idx = idx
    segment_lines = lines[last_start_idx:(complete_idx + 1 if complete_idx is not None else len(lines))]
    steps = []
    current = None
    for i, line in enumerate(segment_lines):
        # Step header
        m = re.match(r"^== STEP (\d+): (.+) ==$", line.strip())
        if m:
            if current is not None:
                steps.append(current)
            current = {"index": int(m.group(1)), "name": m.group(2), "command": None, "returncode": None}
            continue
        if current is not None and line.startswith("COMMAND: "):
            current["command"] = line.split("COMMAND: ", 1)[1].strip()
            continue
        if current is not None and line.strip() == "END:":
            # next line should have returncode
            if i + 1 < len(segment_lines):
                nxt = segment_lines[i + 1].strip()
                if nxt.startswith("returncode="):
                    try:
                        current["returncode"] = int(nxt.split("=", 1)[1])
                    except Exception:
                        current["returncode"] = None
            continue
    if current is not None:
        steps.append(current)
    return {"start_line_idx": last_start_idx, "complete_line_idx": complete_idx, "steps": steps}


def _parse_tests_line(s: str):
    """
    Parse 'Tests: total=<N>, passed=<P>, failed=<F>' and return tuple (N,P,F) or None.
    """
    if not isinstance(s, str):
        return None
    m = re.match(r"^Tests:\s*total=(\d+),\s*passed=(\d+),\s*failed=(\d+)\s*$", s.strip())
    if not m:
        return None
    try:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return None


def _is_semver(s: str) -> bool:
    return isinstance(s, str) and re.fullmatch(r"\d+\.\d+\.\d+", s) is not None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "pipeline_config_step_order_and_commands": 0.0,
        "runner_log_steps_success": 0.0,
        "build_artifacts_valid": 0.0,
        "test_results_valid": 0.0,
        "deploy_summary_consistency": 0.0,
    }

    # Paths
    ci_json_path = workspace / "ci" / "ci.json"
    runner_path = workspace / "tools" / "ci_runner.py"
    build_info_path = workspace / "out" / "build" / "build_info.json"
    app_txt_path = workspace / "out" / "build" / "app.txt"
    test_results_path = workspace / "out" / "test_results.json"
    ci_log_path = workspace / "out" / "logs" / "ci.log"
    project_version_path = workspace / "project" / "VERSION"
    project_commit_path = workspace / "project" / "COMMIT"
    deploy_summary_path = workspace / "out" / "deploy_summary_email.txt"

    # 1) pipeline_config_step_order_and_commands
    cfg = _load_json_safe(ci_json_path)
    if isinstance(cfg, dict) and isinstance(cfg.get("steps"), list) and len(cfg["steps"]) >= 2:
        s0 = cfg["steps"][0]
        s1 = cfg["steps"][1]
        if (
            isinstance(s0, dict)
            and s0.get("name") == "build"
            and s0.get("run") == "python project/build.py"
            and isinstance(s1, dict)
            and s1.get("name") == "tests"
            and s1.get("run") == "python project/tests.py"
        ):
            scores["pipeline_config_step_order_and_commands"] = 1.0

    # 2) runner_log_steps_success
    log_text = _read_text_safe(ci_log_path)
    parsed_run = _parse_ci_last_run(log_text)
    if parsed_run and isinstance(parsed_run.get("steps"), list) and len(parsed_run["steps"]) >= 2:
        steps = parsed_run["steps"]
        step1 = steps[0]
        step2 = steps[1]
        if (
            step1.get("index") == 1
            and step1.get("name") == "build"
            and step1.get("command") == "python project/build.py"
            and step1.get("returncode") == 0
            and step2.get("index") == 2
            and step2.get("name") == "tests"
            and step2.get("command") == "python project/tests.py"
            and step2.get("returncode") == 0
            and parsed_run.get("complete_line_idx") is not None
        ):
            scores["runner_log_steps_success"] = 1.0

    # 3) build_artifacts_valid
    build_info = _load_json_safe(build_info_path)
    app_txt = _read_text_safe(app_txt_path)
    project_version = _read_text_safe(project_version_path).strip()
    project_commit = _read_text_safe(project_commit_path).strip()
    if (
        isinstance(build_info, dict)
        and isinstance(build_info.get("version"), str)
        and isinstance(build_info.get("commit"), str)
        and isinstance(build_info.get("built_at"), str)
        and _is_semver(build_info.get("version"))
        and _is_iso8601_utc_z(build_info.get("built_at"))
        and app_txt != ""
    ):
        version_ok = build_info["version"] == project_version and _is_semver(project_version)
        commit_ok = build_info["commit"] == project_commit and len(project_commit) > 0
        app_line_expected = f"App version {build_info['version']} built from commit {build_info['commit']}"
        app_ok = app_line_expected in app_txt
        if version_ok and commit_ok and app_ok:
            scores["build_artifacts_valid"] = 1.0

    # 4) test_results_valid
    results = _load_json_safe(test_results_path)
    if (
        isinstance(results, dict)
        and isinstance(results.get("total"), int)
        and isinstance(results.get("passed"), int)
        and isinstance(results.get("failed"), int)
        and isinstance(results.get("cases"), list)
    ):
        total = results["total"]
        passed = results["passed"]
        failed = results["failed"]
        cases = results["cases"]
        if total == passed + failed and total == 2 and isinstance(cases, list) and len(cases) == 2:
            scores["test_results_valid"] = 1.0

    # 5) deploy_summary_consistency
    email_text = _read_text_safe(deploy_summary_path)
    email_lines = email_text.splitlines() if email_text else []
    email_ok = False
    if email_lines and email_lines[0].strip() == "Subject: Community Portal CI summary":
        # Collect fields
        commit_line = None
        version_line = None
        built_at_line = None
        tests_line = None
        for line in email_lines[1:]:
            lt = line.strip()
            if lt.startswith("Commit: "):
                commit_line = lt
            elif lt.startswith("Version: "):
                version_line = lt
            elif lt.startswith("Built-At: "):
                built_at_line = lt
            elif lt.startswith("Tests: "):
                tests_line = lt
        if commit_line and version_line and built_at_line and tests_line and isinstance(build_info, dict) and isinstance(results, dict):
            commit_val = commit_line.split("Commit: ", 1)[1].strip()
            version_val = version_line.split("Version: ", 1)[1].strip()
            built_at_val = built_at_line.split("Built-At: ", 1)[1].strip()
            tests_parsed = _parse_tests_line(tests_line)
            # Validate matches
            if (
                commit_val == _read_text_safe(project_commit_path).strip()
                and commit_val == build_info.get("commit")
                and version_val == build_info.get("version")
                and built_at_val == build_info.get("built_at")
                and tests_parsed is not None
            ):
                tn, tp, tf = tests_parsed
                if (
                    isinstance(results.get("total"), int)
                    and isinstance(results.get("passed"), int)
                    and isinstance(results.get("failed"), int)
                    and tn == results["total"]
                    and tp == results["passed"]
                    and tf == results["failed"]
                ):
                    # Check presence of short clear paragraph explaining production and safety to proceed
                    field_labels = {"Commit:", "Version:", "Built-At:", "Tests:"}
                    non_field_lines = []
                    for line in email_lines[1:]:
                        if any(line.strip().startswith(lbl) for lbl in field_labels):
                            continue
                        if line.strip() == "":
                            continue
                        non_field_lines.append(line.strip())
                    # Look for a line with at least 10 words and mentions produced/built and safe/proceed
                    para_ok = False
                    for line in non_field_lines:
                        words = re.findall(r"\w+", line)
                        lower = line.lower()
                        mentions_produced = ("produced" in lower) or ("built" in lower) or ("generated" in lower)
                        mentions_safe = ("safe" in lower) or ("proceed" in lower) or ("ready" in lower)
                        if len(words) >= 10 and mentions_produced and mentions_safe:
                            para_ok = True
                            break
                    if para_ok:
                        email_ok = True
    if email_ok:
        scores["deploy_summary_consistency"] = 1.0

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade(transcript=[], workspace_path=workspace)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()