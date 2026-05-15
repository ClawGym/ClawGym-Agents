import json
import os
import sys
import csv
import re
from collections import OrderedDict

def load_csv_expected(input_csv_path):
    expected_to_delete = []
    expected_to_keep = []
    total_logs = 0
    kept_due_to_policy = 0

    if not os.path.isfile(input_csv_path):
        return None

    with open(input_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = (row.get("filename") or "").strip()
            type_field = (row.get("type") or "").strip()
            age_str = (row.get("age_days") or "").strip()

            # Validate minimal fields
            if not filename or not type_field or age_str == "":
                continue

            # Consider only rows where type == 'log' (case-sensitive per spec, but allow case-insensitive to be robust)
            if type_field.lower() != "log":
                continue

            base = os.path.basename(filename)
            # Only consider .log extension (case-insensitive)
            if not base.lower().endswith(".log"):
                continue

            total_logs += 1

            # Parse age_days as integer
            try:
                age_days = int(float(age_str))
            except Exception:
                # If cannot parse, skip
                continue

            # Policy: KEEP override if name contains 'KEEP' (case-insensitive)
            has_keep = "KEEP" in base.upper()
            if has_keep:
                kept_due_to_policy += 1
                expected_to_keep.append(base)
            else:
                if age_days > 7:
                    expected_to_delete.append(base)
                else:
                    expected_to_keep.append(base)

    # Deduplicate and sort expected lists
    expected_to_delete = sorted(sorted(set(expected_to_delete)))
    expected_to_keep = sorted(sorted(set(expected_to_keep)))

    return {
        "to_delete": expected_to_delete,
        "to_keep": expected_to_keep,
        "total_logs": total_logs,
        "kept_due_to_policy": kept_due_to_policy,
    }

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = OrderedDict()
    for key in [
        "plan_exists",
        "plan_valid_json",
        "plan_sets_match",
        "plan_sorted",
        "plan_deduped",
        "dryrun_exists",
        "dryrun_matches",
        "checksums_exists",
        "checksums_has_fields",
        "checksums_values_match",
        "notes_exists",
        "notes_three_timestamps",
        "notes_workspace_line",
        "notes_cleanup_line",
        "notes_next_steps_line",
    ]:
        checks[key] = False

    # Compute expected from input CSV
    input_csv = os.path.join(input_dir, "log_index.csv")
    expected = load_csv_expected(input_csv)

    # If expected cannot be computed (e.g., missing input), no positive reward can be given
    if expected is None:
        reward = 0.0
        out = OrderedDict()
        out["reward"] = reward
        out.update(checks)
        print(json.dumps(out))
        return

    expected_to_delete = expected["to_delete"]
    expected_to_keep = expected["to_keep"]
    expected_total_logs = expected["total_logs"]
    expected_kept_due_to_policy = expected["kept_due_to_policy"]
    expected_eligible_for_deletion = len(expected_to_delete)

    # 1) Validate cleanup_plan.json
    plan_path = os.path.join(output_dir, "cleanup_plan.json")
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan = read_json_file(plan_path)
        if isinstance(plan, dict) and "to_delete" in plan and "to_keep" in plan:
            if isinstance(plan.get("to_delete"), list) and isinstance(plan.get("to_keep"), list):
                # Ensure all elements are strings
                if all(isinstance(x, str) for x in plan["to_delete"]) and all(isinstance(x, str) for x in plan["to_keep"]):
                    checks["plan_valid_json"] = True
                    # Check sets match
                    plan_to_delete = plan["to_delete"]
                    plan_to_keep = plan["to_keep"]
                    if set(plan_to_delete) == set(expected_to_delete) and set(plan_to_keep) == set(expected_to_keep):
                        checks["plan_sets_match"] = True
                    # Check sorted
                    if plan_to_delete == sorted(plan_to_delete) and plan_to_keep == sorted(plan_to_keep):
                        checks["plan_sorted"] = True
                    # Check deduped
                    if len(plan_to_delete) == len(set(plan_to_delete)) and len(plan_to_keep) == len(set(plan_to_keep)):
                        checks["plan_deduped"] = True

    # 2) Validate cleanup_dryrun.txt
    dryrun_path = os.path.join(output_dir, "cleanup_dryrun.txt")
    if os.path.isfile(dryrun_path):
        checks["dryrun_exists"] = True
        lines = read_lines(dryrun_path)
        if lines is not None:
            # Normalize: strip whitespace, remove blanks
            norm = [ln.strip() for ln in lines if ln.strip() != ""]
            # Must list exactly the to_delete filenames, one per line; order ignored
            if set(norm) == set(expected_to_delete) and len(norm) == len(expected_to_delete):
                checks["dryrun_matches"] = True

    # 3) Validate checksums.json
    checksums_path = os.path.join(output_dir, "checksums.json")
    if os.path.isfile(checksums_path):
        checks["checksums_exists"] = True
        checksums = read_json_file(checksums_path)
        if isinstance(checksums, dict):
            required_fields = ["total_logs", "eligible_for_deletion", "kept_due_to_policy"]
            has_fields = all(k in checksums for k in required_fields)
            # Check integer types
            if has_fields and all(isinstance(checksums[k], int) for k in required_fields):
                checks["checksums_has_fields"] = True
                if (
                    checksums["total_logs"] == expected_total_logs
                    and checksums["eligible_for_deletion"] == expected_eligible_for_deletion
                    and checksums["kept_due_to_policy"] == expected_kept_due_to_policy
                ):
                    checks["checksums_values_match"] = True

    # 4) Validate memory/sprint-notes.md
    notes_path = os.path.join(output_dir, "memory", "sprint-notes.md")
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
        notes_lines = read_lines(notes_path) or []
        # Lines starting with [YYYY-MM-DD HH:MM:SS]
        timestamp_re = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")
        ts_lines = [ln for ln in notes_lines if timestamp_re.match(ln or "")]
        if len(ts_lines) >= 3:
            checks["notes_three_timestamps"] = True

            # Check for Workspace line with total_logs
            workspace_ok = any(("Workspace" in ln and f"total_logs={expected_total_logs}" in ln) for ln in ts_lines)
            if workspace_ok:
                checks["notes_workspace_line"] = True

            # Check for cleanup plan summary line
            cleanup_ok = any(
                (f"eligible_for_deletion={expected_eligible_for_deletion}" in ln
                 and f"kept_due_to_policy={expected_kept_due_to_policy}" in ln
                 and f"total_logs={expected_total_logs}" in ln)
                for ln in ts_lines
            )
            if cleanup_ok:
                checks["notes_cleanup_line"] = True

            # Check for next steps line with actionable item from input/notes_instructions.txt
            notes_instructions_path = os.path.join(input_dir, "notes_instructions.txt")
            actionable_items = set()
            if os.path.isfile(notes_instructions_path):
                inst_lines = read_lines(notes_instructions_path) or []
                for il in inst_lines:
                    s = (il or "").strip()
                    if s:
                        actionable_items.add(s)

            next_steps_ok = False
            for ln in ts_lines:
                if "Next steps:" in ln:
                    # Check inclusion of at least one actionable item as substring
                    for item in actionable_items:
                        if item and item in ln:
                            next_steps_ok = True
                            break
                if next_steps_ok:
                    break
            if next_steps_ok:
                checks["notes_next_steps_line"] = True

    # Weighting for reward calculation
    weights = {
        "plan_exists": 0.05,
        "plan_valid_json": 0.05,
        "plan_sets_match": 0.25,
        "plan_sorted": 0.05,
        "plan_deduped": 0.05,
        "dryrun_exists": 0.05,
        "dryrun_matches": 0.10,
        "checksums_exists": 0.05,
        "checksums_has_fields": 0.05,
        "checksums_values_match": 0.10,
        "notes_exists": 0.05,
        "notes_three_timestamps": 0.05,
        "notes_workspace_line": 0.03,
        "notes_cleanup_line": 0.04,
        "notes_next_steps_line": 0.03,
    }

    # No-op baseline: if output dir missing or empty of required artifacts, many checks remain False and reward becomes 0
    reward = 0.0
    for key, passed in checks.items():
        if passed:
            reward += weights.get(key, 0.0)

    # Clamp reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = OrderedDict()
    result["reward"] = reward
    for k, v in checks.items():
        result[k] = v

    print(json.dumps(result))

if __name__ == "__main__":
    main()