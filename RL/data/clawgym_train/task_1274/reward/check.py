import json
import os
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_sorted_by_key(lst, key):
    keys = [item.get(key, "") for item in lst]
    return keys == sorted(keys)

def compute_expected(input_data):
    # Extract fields with sane defaults
    current_branch = input_data.get("current_branch", "")
    merged_into_main = input_data.get("merged_into_main", [])
    merge_dates = input_data.get("merge_dates", {}) or {}
    branch_tip_dates = input_data.get("branch_tip_dates", {}) or {}

    # Only consider branches listed in merged_into_main; deduplicate
    candidates = sorted(set([b for b in merged_into_main if isinstance(b, str)]))

    expected_renames = []
    expected_skips = []

    for branch in candidates:
        # Skip main/master
        if branch == "main" or branch == "master":
            expected_skips.append({"branch": branch, "reason": "main/master"})
            continue
        # Skip already renamed
        if "--merged-" in branch:
            expected_skips.append({"branch": branch, "reason": "already renamed"})
            continue
        # Skip current checked out branch
        if branch == current_branch:
            expected_skips.append({"branch": branch, "reason": "currently checked out"})
            continue

        used_date = None
        date_source = None

        if branch in merge_dates and merge_dates.get(branch):
            used_date = str(merge_dates.get(branch))
            date_source = "merge"
        elif branch in branch_tip_dates and branch_tip_dates.get(branch):
            used_date = str(branch_tip_dates.get(branch))
            date_source = "tip"

        if not used_date:
            expected_skips.append({"branch": branch, "reason": "could not determine merge date"})
            continue

        new_name = f"{branch}--merged-{used_date}"
        expected_renames.append({
            "branch": branch,
            "new_name": new_name,
            "used_date": used_date,
            "date_source": date_source
        })

    # Ensure sorted by branch ascending
    expected_renames = sorted(expected_renames, key=lambda x: x["branch"])
    expected_skips = sorted(expected_skips, key=lambda x: x["branch"])

    return expected_renames, expected_skips

def validate_rename_plan(path, expected_renames):
    checks = {
        "rename_plan_exists": False,
        "rename_plan_valid_json": False,
        "rename_plan_structure_ok": False,
        "rename_plan_content_match": False
    }

    if not os.path.isfile(path):
        return checks, None

    checks["rename_plan_exists"] = True

    data, err = load_json_file(path)
    if err is not None or not isinstance(data, list):
        return checks, None

    checks["rename_plan_valid_json"] = True

    # Structure check: each item must have exactly the four keys and correct types/values
    allowed_sources = {"merge", "tip"}
    structure_ok = True
    for item in data:
        if not isinstance(item, dict):
            structure_ok = False
            break
        keys = set(item.keys())
        if keys != {"branch", "new_name", "used_date", "date_source"}:
            structure_ok = False
            break
        if not all(isinstance(item[k], str) for k in ["branch", "new_name", "used_date", "date_source"]):
            structure_ok = False
            break
        if item["date_source"] not in allowed_sources:
            structure_ok = False
            break
        # new_name must be branch + "--merged-" + used_date
        if item["new_name"] != f"{item['branch']}--merged-{item['used_date']}":
            structure_ok = False
            break

    if not structure_ok:
        return checks, None

    checks["rename_plan_structure_ok"] = True

    # Content match: must equal expected list exactly (order and content)
    if data == expected_renames:
        checks["rename_plan_content_match"] = True

    return checks, data

def validate_skipped(path, expected_skips):
    checks = {
        "skipped_exists": False,
        "skipped_valid_json": False,
        "skipped_structure_ok": False,
        "skipped_content_match": False
    }

    if not os.path.isfile(path):
        return checks, None

    checks["skipped_exists"] = True

    data, err = load_json_file(path)
    if err is not None or not isinstance(data, list):
        return checks, None

    checks["skipped_valid_json"] = True

    allowed_reasons = {
        "main/master",
        "already renamed",
        "currently checked out",
        "could not determine merge date"
    }

    structure_ok = True
    for item in data:
        if not isinstance(item, dict):
            structure_ok = False
            break
        keys = set(item.keys())
        if keys != {"branch", "reason"}:
            structure_ok = False
            break
        if not isinstance(item.get("branch"), str) or not isinstance(item.get("reason"), str):
            structure_ok = False
            break
        if item.get("reason") not in allowed_reasons:
            structure_ok = False
            break

    if not structure_ok:
        return checks, None

    checks["skipped_structure_ok"] = True

    # Content match: must equal expected list exactly (order and content)
    if data == expected_skips:
        checks["skipped_content_match"] = True

    return checks, data

def validate_summary(path, expected_renames, expected_skips):
    checks = {
        "summary_exists": False,
        "summary_content_match": False
    }

    if not os.path.isfile(path):
        return checks

    checks["summary_exists"] = True

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return checks

    # Normalize line endings and split
    lines = content.splitlines()
    expected_rename_count = len(expected_renames)
    expected_skip_count = len(expected_skips)

    # Must have exactly 2 + number of renames lines
    if len(lines) != 2 + expected_rename_count:
        return checks

    # First two lines exact
    if lines[0] != f"renamed: {expected_rename_count}":
        return checks
    if lines[1] != f"skipped: {expected_skip_count}":
        return checks

    # Subsequent lines must match "BRANCH -> NEW_NAME" for each expected rename in sorted order
    expected_mapping_lines = [f"{item['branch']} -> {item['new_name']}" for item in expected_renames]
    if lines[2:] != expected_mapping_lines:
        return checks

    checks["summary_content_match"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    input_path = os.path.join(input_dir, "branches.json")
    rename_plan_path = os.path.join(output_dir, "rename_plan.json")
    skipped_path = os.path.join(output_dir, "skipped.json")
    summary_path = os.path.join(output_dir, "summary.txt")

    # Initialize checks (artifact-dependent only)
    checks = {
        "rename_plan_exists": False,
        "rename_plan_valid_json": False,
        "rename_plan_structure_ok": False,
        "rename_plan_content_match": False,
        "skipped_exists": False,
        "skipped_valid_json": False,
        "skipped_structure_ok": False,
        "skipped_content_match": False,
        "summary_exists": False,
        "summary_content_match": False
    }

    # If input missing or invalid, we cannot compute expected; reward remains 0
    input_data, input_err = load_json_file(input_path)
    if input_err is not None or not isinstance(input_data, dict):
        # Print result with zero reward
        reward = 0.0
        print(json.dumps({"reward": reward, **checks}))
        return

    expected_renames, expected_skips = compute_expected(input_data)

    # Validate outputs
    rp_checks, _ = validate_rename_plan(rename_plan_path, expected_renames)
    checks.update(rp_checks)

    sk_checks, _ = validate_skipped(skipped_path, expected_skips)
    checks.update(sk_checks)

    sum_checks = validate_summary(summary_path, expected_renames, expected_skips)
    checks.update(sum_checks)

    # Compute reward as fraction of passed checks among artifact-dependent validations
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if no relevant output files present, ensure reward is 0.0
    any_output_present = any(os.path.isfile(p) for p in [rename_plan_path, skipped_path, summary_path])
    if not any_output_present:
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()