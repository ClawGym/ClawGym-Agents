import json
import re
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_simple_kv_config(path: Path) -> dict:
    """
    Minimal parser matching tools/ci_runner.py expectations: key: value per line, no nesting.
    Ignores comments and blank lines.
    """
    txt = _read_text(path)
    if txt is None:
        return {}
    cfg = {}
    for raw in txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def _strip_optional_quotes(s: str) -> str:
    if not isinstance(s, str):
        return s
    s = s.strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s


def _normalize_spaces(s: str) -> str:
    return " ".join((s or "").split())


def _count_tests_in_file(path: Path) -> int:
    """
    Count number of tests by finding occurrences of 'total += 1' in tests/run_tests.py.
    """
    txt = _read_text(path)
    if txt is None:
        return 0
    count = 0
    for raw in txt.splitlines():
        line = raw
        # ignore comments
        if "#" in line:
            code, _ = line.split("#", 1)
        else:
            code = line
        if re.search(r"\btotal\s*\+\=\s*1\b", code):
            count += 1
    return count


def _is_single_line_under_limit(s: str, limit: int) -> bool:
    if s is None:
        return False
    # Allow trailing newline; consider content lines
    lines = s.rstrip("\r\n").splitlines()
    if len(lines) != 1:
        return False
    return len(lines[0]) <= limit


def _find_first_paragraph(text: str) -> str:
    if not text:
        return ""
    # Split on blank lines
    paras = []
    current = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                paras.append("\n".join(current).strip())
                current = []
        else:
            current.append(line)
    if current:
        paras.append("\n".join(current).strip())
    return paras[0] if paras else ""


def _count_sentences(text: str) -> int:
    # Split by sentence delimiters . ! ?
    if not text:
        return 0
    parts = re.split(r"[.!?]+", text)
    cnt = 0
    for p in parts:
        if re.search(r"[A-Za-z0-9]", p):
            cnt += 1
    return cnt


def _line_contains_key_value(lines, key_substr: str, value_str: str) -> bool:
    key_substr_lower = key_substr.lower()
    value_str_lower = value_str.lower()
    for line in lines:
        l = line.strip().lower()
        if key_substr_lower in l and value_str_lower in l:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ci_config_command_fixed": 0.0,
        "ci_report_exists_and_fields": 0.0,
        "ci_report_status_valid": 0.0,
        "ci_report_command_matches_config": 0.0,
        "ci_report_counts_consistent": 0.0,
        "ci_status_matches_counts": 0.0,
        "ci_duration_valid": 0.0,
        "notifications_single_line_under_160_includes_status_and_counts": 0.0,
        "status_update_has_metrics_and_values": 0.0,
        "status_update_has_summary_2_to_3_sentences": 0.0,
        "status_update_has_changelog_entries": 0.0,
    }

    # Paths
    ci_config_path = workspace / "ci" / "config.yaml"
    report_path = workspace / "out" / "ci_report.json"
    notif_path = workspace / "out" / "notifications_clean.txt"
    status_md_path = workspace / "out" / "status_update.md"
    tests_file_path = workspace / "tests" / "run_tests.py"

    # Load config
    cfg = _parse_simple_kv_config(ci_config_path)
    cfg_cmd_raw = cfg.get("test_command")
    cfg_cmd = _strip_optional_quotes(cfg_cmd_raw) if cfg_cmd_raw is not None else None

    # Check config command fixed
    try:
        cmd_ok = False
        if isinstance(cfg_cmd, str):
            norm_cmd = _normalize_spaces(cfg_cmd).strip()
            lc = norm_cmd.lower()
            starts_python = lc.startswith("python ") or lc.startswith("python3 ")
            contains_correct = "tests/run_tests.py" in lc
            contains_incorrect = "tests/run_test.py" in lc  # the buggy one
            if starts_python and contains_correct and not contains_incorrect:
                cmd_ok = True
        scores["ci_config_command_fixed"] = 1.0 if cmd_ok else 0.0
    except Exception:
        scores["ci_config_command_fixed"] = 0.0

    # Load report
    report = _load_json(report_path)
    if isinstance(report, dict):
        # Validate required fields and types
        required_fields_present = all(
            k in report for k in ["status", "tests_passed", "tests_failed", "duration_seconds", "command"]
        )
        types_ok = isinstance(report.get("status"), str) and isinstance(report.get("command"), str)
        # tests_passed and tests_failed should be integers
        counts_ok = isinstance(report.get("tests_passed"), int) and isinstance(report.get("tests_failed"), int)
        duration_ok = isinstance(report.get("duration_seconds"), (int, float))
        if required_fields_present and types_ok and counts_ok and duration_ok:
            scores["ci_report_exists_and_fields"] = 1.0

        # Status valid (success or failure, not error)
        status_val = str(report.get("status", "")).lower()
        if status_val in {"success", "failure"}:
            scores["ci_report_status_valid"] = 1.0

        # Command matches config exactly (normalized)
        report_cmd = _normalize_spaces(_strip_optional_quotes(report.get("command", "")))
        cfg_cmd_norm = _normalize_spaces(_strip_optional_quotes(cfg_cmd)) if cfg_cmd else ""
        if report_cmd == cfg_cmd_norm and report_cmd != "":
            scores["ci_report_command_matches_config"] = 1.0

        # Duration non-negative
        try:
            dur = float(report.get("duration_seconds"))
            if dur >= 0.0:
                scores["ci_duration_valid"] = 1.0
        except Exception:
            pass

        # Counts consistency with tests file
        expected_tests = _count_tests_in_file(tests_file_path)
        tp = report.get("tests_passed")
        tf = report.get("tests_failed")
        if isinstance(tp, int) and isinstance(tf, int):
            if expected_tests > 0 and tp >= 0 and tf >= 0 and (tp + tf) == expected_tests:
                scores["ci_report_counts_consistent"] = 1.0
            # Status matches counts rule
            if status_val == "success" and tf == 0:
                scores["ci_status_matches_counts"] = 1.0
            elif status_val == "failure" and tf > 0:
                scores["ci_status_matches_counts"] = 1.0

        # Notifications checks
        notif_txt = _read_text(notif_path)
        if notif_txt is not None:
            single_line_ok = _is_single_line_under_limit(notif_txt, 160)
            # Presence of actual status and counts
            has_status = str(report.get("status", "")).lower() in notif_txt.lower()
            has_passed = str(report.get("tests_passed")) in notif_txt
            has_failed = str(report.get("tests_failed")) in notif_txt
            if single_line_ok and has_status and has_passed and has_failed:
                scores["notifications_single_line_under_160_includes_status_and_counts"] = 1.0

        # Status update markdown checks
        md_txt = _read_text(status_md_path)
        if md_txt is not None:
            lines = md_txt.splitlines()

            # Metrics and values presence
            metrics_ok = True
            # pipeline_status with actual status
            if not _line_contains_key_value(lines, "pipeline_status", str(report.get("status", ""))):
                metrics_ok = False
            # tests_passed with value
            if not _line_contains_key_value(lines, "tests_passed", str(report.get("tests_passed"))):
                metrics_ok = False
            # tests_failed with value
            if not _line_contains_key_value(lines, "tests_failed", str(report.get("tests_failed"))):
                metrics_ok = False
            # duration_seconds rounded to nearest tenth
            try:
                dur = float(report.get("duration_seconds"))
                dur_rounded_str = f"{round(dur, 1):.1f}"
            except Exception:
                dur_rounded_str = None
            if not (dur_rounded_str and _line_contains_key_value(lines, "duration_seconds", dur_rounded_str)):
                metrics_ok = False
            # command used present somewhere
            cmd_present = any(_normalize_spaces(_strip_optional_quotes(report.get("command", ""))) in line for line in lines)
            if not cmd_present:
                metrics_ok = False
            if metrics_ok:
                scores["status_update_has_metrics_and_values"] = 1.0

            # Summary 2–3 sentences
            para = _find_first_paragraph(md_txt)
            sent_count = _count_sentences(para)
            if 2 <= sent_count <= 3:
                scores["status_update_has_summary_2_to_3_sentences"] = 1.0

            # Changelog bullets mentioning config fix and communication artifacts
            bullet_lines = [ln.strip() for ln in lines if ln.strip().startswith(("-", "*"))]
            mentions_config = any(re.search(r"\bconfig\b", bl, flags=re.IGNORECASE) or "ci/config.yaml" in bl for bl in bullet_lines)
            mentions_comms = any(
                re.search(r"\bnotification|notifications|status|message|report\b", bl, flags=re.IGNORECASE)
                or "out/notifications_clean.txt" in bl
                or "out/status_update.md" in bl
                or "out/ci_report.json" in bl
                for bl in bullet_lines
            )
            if bullet_lines and mentions_config and mentions_comms:
                scores["status_update_has_changelog_entries"] = 1.0

    else:
        # If report is missing or malformed, related checks remain 0.0
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()