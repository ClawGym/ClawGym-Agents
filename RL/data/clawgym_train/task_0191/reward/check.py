import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "validate_log_ok": False,
        "dry_run_has_dry": False,
        "run_log_complete_and_retry": False,
        "report_format_ok": False,
        "conditional_behavior_ok": False,
        "summary_json_ok": False,
    }

    # Reference message from input/vars.json (no credit for merely reading it; used for comparisons)
    expected_message = None
    vars_json_path = os.path.join(input_dir, "vars.json")
    vars_json = load_json(vars_json_path)
    if isinstance(vars_json, dict):
        msg = vars_json.get("message")
        if isinstance(msg, str):
            expected_message = msg

    # 1) Validate log check: must contain a line starting with "VALID:"
    validate_log_path = os.path.join(output_dir, "logs", "validate.txt")
    validate_lines = read_lines(validate_log_path)
    if validate_lines is not None:
        for line in validate_lines:
            if line.lstrip().startswith("VALID:"):
                checks["validate_log_ok"] = True
                break

    # 2) Dry run log must include "[DRY]"
    dry_run_log_path = os.path.join(output_dir, "logs", "dry_run.txt")
    dry_text = read_text(dry_run_log_path)
    if dry_text is not None and "[DRY]" in dry_text:
        checks["dry_run_has_dry"] = True

    # 3) Run log must include "WORKFLOW COMPLETE:" and "RETRY"
    run_log_path = os.path.join(output_dir, "logs", "run.txt")
    run_text = read_text(run_log_path)
    if run_text is not None and "WORKFLOW COMPLETE:" in run_text and "RETRY" in run_text:
        checks["run_log_complete_and_retry"] = True

    # 4) Report file content: two lines with ID and Message matching expected_message
    report_path = os.path.join(output_dir, "report.txt")
    report_lines = read_lines(report_path)
    parsed_id = None
    msg_ok = False
    id_ok = False
    if report_lines is not None:
        for line in report_lines:
            if line.startswith("ID:"):
                candidate = line[len("ID:"):].strip()
                if candidate:
                    parsed_id = candidate
                    id_ok = True
            elif line.startswith("Message:"):
                candidate_msg = line[len("Message:"):].strip()
                if expected_message is not None and candidate_msg == expected_message:
                    msg_ok = True
        if id_ok and msg_ok:
            checks["report_format_ok"] = True

    # 5) Conditional behavior: if conditional.txt exists, it must include "ok"; if not, run log must show it was skipped
    conditional_path = os.path.join(output_dir, "conditional.txt")
    if os.path.isfile(conditional_path):
        cond_text = read_text(conditional_path)
        if cond_text is not None and "ok" in cond_text:
            checks["conditional_behavior_ok"] = True
    else:
        # If it doesn't exist, ensure run log shows a SKIP for the conditional step
        if run_text is not None and "SKIP [" in run_text:
            checks["conditional_behavior_ok"] = True

    # 6) Summary JSON checks
    summary_path = os.path.join(output_dir, "summary.json")
    summary = load_json(summary_path)
    if isinstance(summary, dict):
        # Fields: id (string), message (string), conditional_written (bool)
        id_field = summary.get("id")
        msg_field = summary.get("message")
        cond_written = summary.get("conditional_written")
        cond_exists = os.path.isfile(conditional_path)

        id_match = isinstance(id_field, str) and isinstance(parsed_id, str) and id_field == parsed_id
        msg_match = isinstance(msg_field, str) and isinstance(expected_message, str) and msg_field == expected_message
        cond_match = isinstance(cond_written, bool) and cond_written == cond_exists

        if id_match and msg_match and cond_match:
            checks["summary_json_ok"] = True

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir is missing or empty and no checks passed, reward must be 0.0
    # Our formula already yields 0.0 if no checks passed.
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()