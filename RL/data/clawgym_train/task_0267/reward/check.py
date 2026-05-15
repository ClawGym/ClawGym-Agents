import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = read_text_safe(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def run_checker(workspace: Path, compose_rel_path: str) -> Optional[Dict[str, Any]]:
    checker = workspace / "tools" / "check.py"
    if not checker.exists():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(checker), compose_rel_path],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
        output = proc.stdout.strip()
        return json.loads(output) if output else None
    except Exception:
        return None


def contains_subsequence(seq: List[str], subseq: List[str]) -> bool:
    if not subseq:
        return True
    i = 0
    for item in seq:
        if item == subseq[i]:
            i += 1
            if i == len(subseq):
                return True
    return False


def has_screening_mode_default_hybrid(compose_text: str) -> bool:
    # Accept both list-style and mapping-style environment definitions
    # Examples:
    # - SCREENING_MODE=${SCREENING_MODE:-hybrid}
    # SCREENING_MODE: ${SCREENING_MODE:-hybrid}
    pattern = r"SCREENING_MODE\s*(?:=|:)\s*[\"']?\$\{\s*SCREENING_MODE\s*:-\s*hybrid\s*\}[\"']?"
    return re.search(pattern, compose_text) is not None


def has_app_port_5000(compose_text: str) -> bool:
    # Accept both "- APP_PORT=5000" and "APP_PORT: '5000'"
    pattern = r"APP_PORT\s*(?:=|:)\s*[\"']?5000[\"']?(?:\b|[^0-9])"
    return re.search(pattern, compose_text) is not None


def has_ports_5000(compose_text: str) -> bool:
    # Accept quoted or unquoted "5000:5000"
    return re.search(r"['\"]?5000:5000['\"]?", compose_text) is not None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "fixed_compose_exists": 0.0,
        "fixed_compose_has_web_service_and_build_context": 0.0,
        "fixed_compose_env_screening_mode_default_hybrid": 0.0,
        "fixed_compose_env_app_port_5000": 0.0,
        "fixed_compose_ports_mapping_5000": 0.0,
        "fixed_compose_no_screenin_mode_typo": 0.0,
        "report_exists_and_structure": 0.0,
        "report_before_checker_match": 0.0,
        "report_after_checker_match": 0.0,
        "before_check_status_fail": 0.0,
        "after_check_status_pass": 0.0,
        "commands_executed_include_checker_runs": 0.0,
        "logs_diagnosis_includes_key_lines": 0.0,
        "fixed_issues_list_mentions_env_and_hybrid": 0.0,
        "email_exists": 0.0,
        "email_has_subject_line": 0.0,
        "email_mentions_hybrid_default_and_override_instructions": 0.0,
        "email_run_command_uses_fixed_compose": 0.0,
    }

    # Paths
    input_compose_rel = "input/docker-compose.yml"
    fixed_compose_rel = "out/docker-compose.fixed.yml"
    report_rel = "out/deployment_report.json"
    email_rel = "out/email_to_team.txt"
    logs_rel = "input/logs/run_output.txt"

    input_compose_path = workspace / input_compose_rel
    fixed_compose_path = workspace / fixed_compose_rel
    report_path = workspace / report_rel
    email_path = workspace / email_rel
    logs_path = workspace / logs_rel

    # Validate fixed compose file
    fixed_text = read_text_safe(fixed_compose_path)
    if fixed_text is not None:
        scores["fixed_compose_exists"] = 1.0

        # Must have web service and build context
        has_services = "services:" in fixed_text
        has_web = re.search(r"^\s*web\s*:\s*$", fixed_text, re.MULTILINE) is not None or "web:" in fixed_text
        has_build = "build:" in fixed_text
        has_context_dot = re.search(r"^\s*context\s*:\s*\.\s*$", fixed_text, re.MULTILINE) is not None or "context: ." in fixed_text
        if has_services and has_web and has_build and has_context_dot:
            scores["fixed_compose_has_web_service_and_build_context"] = 1.0

        # SCREENING_MODE default "hybrid"
        if has_screening_mode_default_hybrid(fixed_text):
            scores["fixed_compose_env_screening_mode_default_hybrid"] = 1.0

        # Ensure typo SCREENIN_MODE is not present in fixed file
        if "SCREENIN_MODE" not in fixed_text:
            scores["fixed_compose_no_screenin_mode_typo"] = 1.0

        # APP_PORT=5000 or mapping variant
        if has_app_port_5000(fixed_text):
            scores["fixed_compose_env_app_port_5000"] = 1.0

        # Ports mapping 5000:5000 (quotes optional)
        if has_ports_5000(fixed_text):
            scores["fixed_compose_ports_mapping_5000"] = 1.0

    # Report validation
    report = load_json_safe(report_path)
    if isinstance(report, dict):
        required_fields = [
            "before_check",
            "after_check",
            "diagnosed_from_logs",
            "fixed_issues",
            "compose_fixed_path",
            "commands_executed",
        ]
        types_ok = (
            isinstance(report.get("before_check"), dict)
            and isinstance(report.get("after_check"), dict)
            and isinstance(report.get("diagnosed_from_logs"), list)
            and isinstance(report.get("fixed_issues"), list)
            and isinstance(report.get("compose_fixed_path"), str)
            and isinstance(report.get("commands_executed"), list)
        )
        path_ok = report.get("compose_fixed_path") == fixed_compose_rel
        if all(k in report for k in required_fields) and types_ok and path_ok:
            scores["report_exists_and_structure"] = 1.0

        # Compare checker outputs exactly
        before_actual = run_checker(workspace, input_compose_rel)
        after_actual = run_checker(workspace, fixed_compose_rel)
        before_report = report.get("before_check") if isinstance(report.get("before_check"), dict) else None
        after_report = report.get("after_check") if isinstance(report.get("after_check"), dict) else None

        if before_actual is not None and before_report is not None and before_actual == before_report:
            scores["report_before_checker_match"] = 1.0
        if after_actual is not None and after_report is not None and after_actual == after_report:
            scores["report_after_checker_match"] = 1.0

        # Status checks
        if isinstance(before_actual, dict) and before_actual.get("status") == "fail":
            scores["before_check_status_fail"] = 1.0
        if isinstance(after_actual, dict) and after_actual.get("status") == "pass":
            scores["after_check_status_pass"] = 1.0

        # Commands executed should include the two checker runs in order
        cmds = report.get("commands_executed")
        if isinstance(cmds, list):
            expected = [
                "python tools/check.py input/docker-compose.yml",
                "python tools/check.py out/docker-compose.fixed.yml",
            ]
            if contains_subsequence([str(c) for c in cmds], expected):
                scores["commands_executed_include_checker_runs"] = 1.0

        # Logs diagnosis: ensure items are drawn from the provided logs and include the key error message
        logs_text = read_text_safe(logs_path) or ""
        diag_list = report.get("diagnosed_from_logs")
        if isinstance(diag_list, list) and logs_text:
            all_present = all(isinstance(x, str) and x in logs_text for x in diag_list)
            key1 = "Environment variable SCREENING_MODE is required"
            key2 = "ERROR: App failed to start due to missing SCREENING_MODE"
            includes_key = any(isinstance(x, str) and (key1 in x or key2 in x) for x in diag_list)
            if all_present and includes_key:
                scores["logs_diagnosis_includes_key_lines"] = 1.0

        # Fixed issues: mention env var correction and chosen default "hybrid"
        fixed_issues = report.get("fixed_issues")
        if isinstance(fixed_issues, list):
            joined = " ".join([str(i) for i in fixed_issues]).lower()
            if ("screening_mode" in joined) and ("hybrid" in joined):
                scores["fixed_issues_list_mentions_env_and_hybrid"] = 1.0

    # Email validation
    email_text = read_text_safe(email_path)
    if email_text is not None:
        scores["email_exists"] = 1.0
        lines = [ln.strip() for ln in email_text.splitlines() if ln.strip() != ""]
        if lines and lines[0].lower().startswith("subject:"):
            scores["email_has_subject_line"] = 1.0
        # Mention SCREENING_MODE default hybrid and override guidance (theatrical / streaming)
        if ("SCREENING_MODE" in email_text and "hybrid" in email_text.lower()
                and ("theatrical" in email_text.lower()) and ("streaming" in email_text.lower())):
            scores["email_mentions_hybrid_default_and_override_instructions"] = 1.0
        # Include the exact run command
        if "docker compose -f out/docker-compose.fixed.yml up" in email_text:
            scores["email_run_command_uses_fixed_compose"] = 1.0

    return scores


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Grader for RSVP microservice compose fix task")
    ap.add_argument("workspace_path", nargs="?", default=".")
    args = ap.parse_args()
    result = grade([], args.workspace_path)
    json.dump(result, sys.stdout, indent=2)


if __name__ == "__main__":
    main()