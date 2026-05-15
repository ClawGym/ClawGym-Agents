import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def is_int_percent(s):
    if not isinstance(s, str):
        return False, None
    m = re.fullmatch(r"([0-9]{1,3})%", s.strip())
    if not m:
        return False, None
    val = int(m.group(1))
    if 0 <= val <= 100:
        return True, val
    return False, None

def nonempty_fields(cols):
    return all(isinstance(c, str) and len(c) > 0 for c in cols)

def check_readme_commands(content):
    if content is None:
        return False
    low = content.lower()
    return ("start" in low) and ("stop" in low) and ("status" in low)

def check_requirements(content):
    if content is None:
        return False
    low = content.lower()
    return ("requests" in low) and ("pyyaml" in low)

def check_env_api_key(content):
    if content is None:
        return False
    # Case-insensitive line starting with API_KEY=
    return re.search(r"(?im)^\s*api_key\s*=", content) is not None

def check_gitignore_pycache(content):
    if content is None:
        return False
    return "__pycache__/" in content

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    results_tsv_path = os.path.join(output_dir, "results", "demo-repo-results.tsv")
    proposed_dir = os.path.join(output_dir, "results", "demo-repo-proposed")
    proposed_readme = os.path.join(proposed_dir, "README.md")
    proposed_requirements = os.path.join(proposed_dir, "requirements.txt")
    proposed_env = os.path.join(proposed_dir, "env.example.txt")
    proposed_gitignore = os.path.join(proposed_dir, "gitignore.txt")

    checks = {
        "tsv_exists": False,
        "tsv_header_ok": False,
        "tsv_min_rows": False,
        "tsv_row2_baseline": False,
        "tsv_row3_improved": False,
        "tsv_pass_rates_format": False,
        "tsv_improved_higher": False,
        "tsv_pvs_len_ok": False,
        "tsv_change_desc_len_ok": False,
        "tsv_columns_ok_nonempty": False,
        "tsv_status_values_ok": False,
        "proposed_dir_exists": False,
        "proposed_readme_ok": False,
        "proposed_requirements_ok": False,
        "proposed_env_ok": False,
        "proposed_gitignore_ok": False,
    }

    # TSV checks
    lines = read_lines(results_tsv_path)
    if lines is not None:
        checks["tsv_exists"] = True
        if len(lines) >= 1:
            # Normalize potential BOM on first line
            header_line = lines[0].lstrip("\ufeff")
            expected_header = "iteration\tprompt_version_summary\tpass_rate\tchange_description\tstatus"
            if header_line == expected_header:
                checks["tsv_header_ok"] = True

        data_rows = lines[1:] if len(lines) >= 2 else []
        if len(data_rows) >= 2:
            checks["tsv_min_rows"] = True

        # Validate rows
        allowed_statuses = {"baseline", "improved", "retained", "discard"}
        all_passrate_ok = True
        all_pvs_len_ok = True
        all_change_desc_len_ok = True
        all_cols_ok_nonempty = True
        all_status_values_ok = True

        baseline_rate = None
        improved_rate = None

        for idx, raw in enumerate(data_rows):
            # Count tabs and split
            cols = raw.split("\t")
            if len(cols) != 5:
                all_cols_ok_nonempty = False
                all_status_values_ok = False
                all_passrate_ok = False
                all_pvs_len_ok = False
                all_change_desc_len_ok = False
                continue

            iter_col, pvs, pr_str, change_desc, status = cols

            # Non-empty fields
            if not nonempty_fields(cols):
                all_cols_ok_nonempty = False

            # Length checks
            if len(pvs) > 50:
                all_pvs_len_ok = False
            if len(change_desc) > 100:
                all_change_desc_len_ok = False

            # Status values
            if status not in allowed_statuses:
                all_status_values_ok = False

            # Pass rate format
            ok_fmt, val = is_int_percent(pr_str)
            if not ok_fmt:
                all_passrate_ok = False

            # Capture baseline (row 0) and improved (row 1) pass rates
            if idx == 0 and ok_fmt:
                baseline_rate = val
            if idx == 1 and ok_fmt:
                improved_rate = val

        checks["tsv_pass_rates_format"] = all_passrate_ok and len(data_rows) >= 1
        checks["tsv_pvs_len_ok"] = all_pvs_len_ok and len(data_rows) >= 1
        checks["tsv_change_desc_len_ok"] = all_change_desc_len_ok and len(data_rows) >= 1
        checks["tsv_columns_ok_nonempty"] = all_cols_ok_nonempty and len(data_rows) >= 1
        checks["tsv_status_values_ok"] = all_status_values_ok and len(data_rows) >= 1

        # Specific row checks for statuses
        if len(data_rows) >= 1:
            row2_cols = data_rows[0].split("\t")
            if len(row2_cols) == 5 and row2_cols[4] == "baseline":
                checks["tsv_row2_baseline"] = True
        if len(data_rows) >= 2:
            row3_cols = data_rows[1].split("\t")
            if len(row3_cols) == 5 and row3_cols[4] == "improved":
                checks["tsv_row3_improved"] = True

        # Improved higher than baseline
        if baseline_rate is not None and improved_rate is not None and improved_rate > baseline_rate:
            checks["tsv_improved_higher"] = True

    # Proposed files checks
    if os.path.isdir(proposed_dir):
        checks["proposed_dir_exists"] = True

        readme_content = read_text(proposed_readme)
        if readme_content is not None and check_readme_commands(readme_content):
            checks["proposed_readme_ok"] = True

        reqs_content = read_text(proposed_requirements)
        if reqs_content is not None and check_requirements(reqs_content):
            checks["proposed_requirements_ok"] = True

        env_content = read_text(proposed_env)
        if env_content is not None and check_env_api_key(env_content):
            checks["proposed_env_ok"] = True

        gitignore_content = read_text(proposed_gitignore)
        if gitignore_content is not None and check_gitignore_pycache(gitignore_content):
            checks["proposed_gitignore_ok"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # No-op baseline override: if output missing or both key artifacts missing, reward = 0.0
    if (not os.path.isdir(output_dir)) or (not checks["tsv_exists"] and not checks["proposed_dir_exists"]):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()