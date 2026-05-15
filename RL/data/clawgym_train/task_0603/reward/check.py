import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return []

def count_pipes(line: str) -> int:
    return line.count("|")

def extract_first_int(pattern: str, text: str):
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def has_oneline_shape(lines, id_prefix):
    # Check for at least one line beginning with [YYYY- and containing id prefix and >=3 pipes
    for line in lines:
        if line.startswith("[") and "id:" + id_prefix in line:
            # Quick date check [YYYY-
            if re.match(r"^\[[0-9]{4}-", line) and count_pipes(line) >= 3:
                return True
    return False

def get_pending_lines(lines):
    return [ln for ln in lines if "status: pending" in ln]

def json_last_print(obj):
    # Print exactly one JSON object as the last non-empty line
    print(json.dumps(obj, separators=(",", ":")))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    errors_path = os.path.join(output_dir, ".learnings", "errors.md")
    learnings_path = os.path.join(output_dir, ".learnings", "learnings.md")
    wishes_path = os.path.join(output_dir, ".learnings", "wishes.md")
    pqueue_path = os.path.join(output_dir, ".learnings", "promotion-queue.md")
    pre_task_review_path = os.path.join(output_dir, "pre-task-review.md")
    review_summary_path = os.path.join(output_dir, "review-summary.json")

    checks = {
        "has_errors_file": False,
        "has_learnings_file": False,
        "has_wishes_file": False,
        "has_pqueue_file": False,
        "learnings_has_entry": False,
        "learnings_LRN20260302_count_ge3": False,
        "errors_has_err_entry": False,
        "has_prevented_ge1": False,
        "pqueue_pending_two_plus": False,
        "pqueue_no_external": False,
        "pre_task_review_ok": False,
        "review_summary_ok": False,
        "errors_oneline_shape_ok": False,
        "learnings_oneline_shape_ok": False,
        "pqueue_shaped_pending_lines": False,
    }

    # Existence checks
    checks["has_errors_file"] = os.path.isfile(errors_path)
    checks["has_learnings_file"] = os.path.isfile(learnings_path)
    checks["has_wishes_file"] = os.path.isfile(wishes_path)
    checks["has_pqueue_file"] = os.path.isfile(pqueue_path)

    # Load file contents
    errors_lines = read_lines(errors_path) if checks["has_errors_file"] else []
    learnings_lines = read_lines(learnings_path) if checks["has_learnings_file"] else []
    pqueue_lines = read_lines(pqueue_path) if checks["has_pqueue_file"] else []
    pre_task_review_text = read_text(pre_task_review_path) if os.path.isfile(pre_task_review_path) else ""
    review_summary_text = read_text(review_summary_path) if os.path.isfile(review_summary_path) else ""

    # Learnings has at least one LRN entry
    if checks["has_learnings_file"]:
        checks["learnings_has_entry"] = any(
            ln.startswith("[") and "id:LRN-" in ln for ln in learnings_lines
        )

    # Check id:LRN-20260302-001 count >=3
    if checks["has_learnings_file"]:
        found_target = False
        for ln in learnings_lines:
            if "id:LRN-20260302-001" in ln:
                found_target = True
                cnt = extract_first_int(r"count:\s*([0-9]+)", ln)
                if cnt is not None and cnt >= 3:
                    checks["learnings_LRN20260302_count_ge3"] = True
                    break
        # If not found, remains False

    # Errors has id:ERR-
    if checks["has_errors_file"]:
        checks["errors_has_err_entry"] = any("id:ERR-" in ln for ln in errors_lines)

    # prevented >=1 somewhere in learnings or errors
    prevented_found = False
    for ln in (learnings_lines + errors_lines):
        m = re.search(r"prevented:\s*([0-9]+)", ln)
        if m:
            try:
                val = int(m.group(1))
                if val >= 1:
                    prevented_found = True
                    break
            except Exception:
                pass
    checks["has_prevented_ge1"] = prevented_found

    # Promotion queue checks
    if checks["has_pqueue_file"]:
        pending_lines = get_pending_lines(pqueue_lines)
        checks["pqueue_pending_two_plus"] = len(pending_lines) >= 2
        full_text = "".join(pqueue_lines)
        checks["pqueue_no_external"] = ("source:external" not in full_text)
        # Shape check for queued items: line starts with [, includes id:, target:, status: pending
        shaped_count = 0
        for ln in pending_lines:
            if ln.strip().startswith("[") and "id:" in ln and "target:" in ln and "status: pending" in ln:
                shaped_count += 1
        checks["pqueue_shaped_pending_lines"] = shaped_count >= 2

    # Pre-task review
    if os.path.isfile(pre_task_review_path):
        has_adjustments = ("Adjustments:" in pre_task_review_text)
        has_id = ("id:LRN-" in pre_task_review_text)
        checks["pre_task_review_ok"] = has_adjustments and has_id

    # review-summary.json validation
    review_ok = False
    if os.path.isfile(review_summary_path):
        try:
            data = json.loads(review_summary_text)
            # Required keys
            if (
                isinstance(data, dict)
                and "files" in data
                and "queued_pending" in data
                and "total_prevented" in data
                and isinstance(data["files"], dict)
            ):
                files = data["files"]
                required_files_keys = ["errors", "learnings", "wishes", "promotion_queue"]
                files_ok = all(k in files for k in required_files_keys)
                types_ok = (
                    isinstance(data["queued_pending"], int)
                    and isinstance(data["total_prevented"], int)
                    and all(isinstance(files[k], int) for k in required_files_keys)
                )
                review_ok = files_ok and types_ok
        except Exception:
            review_ok = False
    checks["review_summary_ok"] = review_ok

    # One-line format shape checks (rubric)
    if checks["has_errors_file"]:
        checks["errors_oneline_shape_ok"] = has_oneline_shape(errors_lines, "ERR-")
    if checks["has_learnings_file"]:
        checks["learnings_oneline_shape_ok"] = has_oneline_shape(learnings_lines, "LRN-")

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    result = {"reward": reward}
    result.update(checks)
    json_last_print(result)

if __name__ == "__main__":
    main()