import json
import os
import re
import sys

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
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
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected artifacts and contents
    expected_entries = {
        "bash - Loops: for i in $(seq 1 5); do echo $i; done",
        "git - Undo last commit: git reset --soft HEAD~1",
        "python - Virtual env: python -m venv .venv && source .venv/bin/activate",
    }
    expected_search_map = {
        "git": ["git - Undo last commit: git reset --soft HEAD~1"],
        "virtual": ["python - Virtual env: python -m venv .venv && source .venv/bin/activate"],
        "loops": ["bash - Loops: for i in $(seq 1 5); do echo $i; done"],
    }

    cli_export_path = os.path.join(output_dir, "exports", "cli_export.txt")
    entries_json_path = os.path.join(output_dir, "exports", "entries.json")
    search_results_path = os.path.join(output_dir, "search", "search_results.json")
    status_txt_path = os.path.join(output_dir, "meta", "status.txt")

    checks = {
        "has_cli_export_file": False,
        "cli_export_contains_expected_entries": False,
        "cli_export_date_prefixes_valid": False,

        "has_entries_json": False,
        "entries_json_valid_format": False,
        "entries_json_contains_exact_entries": False,

        "has_search_results_json": False,
        "search_results_json_valid_format": False,
        "search_results_json_exact_matches": False,

        "has_status_txt": False,
        "status_contains_version": False,
        "status_contains_data_dir": False,
        "status_contains_ready": False,
    }

    # Check cli_export.txt
    if os.path.isfile(cli_export_path):
        checks["has_cli_export_file"] = True
        text = load_text(cli_export_path)
        if text is not None:
            lines = [ln.rstrip("\n\r") for ln in text.splitlines() if ln.strip() != ""]
            matched = set()
            # For each expected entry, find a line with correct prefix and suffix
            for exp in expected_entries:
                found = False
                for ln in lines:
                    if ln.endswith(exp):
                        # Verify date prefix at start "YYYY-MM-DD "
                        if re.match(r"^\d{4}-\d{2}-\d{2} ", ln):
                            found = True
                            break
                if found:
                    matched.add(exp)
            if matched == expected_entries:
                checks["cli_export_contains_expected_entries"] = True
                checks["cli_export_date_prefixes_valid"] = True

    # Check entries.json
    if os.path.isfile(entries_json_path):
        checks["has_entries_json"] = True
        data = load_json(entries_json_path)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            checks["entries_json_valid_format"] = True
            data_set = set(data)
            if len(data) == 3 and data_set == expected_entries:
                checks["entries_json_contains_exact_entries"] = True

    # Check search_results.json
    if os.path.isfile(search_results_path):
        checks["has_search_results_json"] = True
        data = load_json(search_results_path)
        if isinstance(data, dict):
            # keys exactly git, virtual, loops
            expected_keys = set(expected_search_map.keys())
            if set(data.keys()) == expected_keys and all(isinstance(v, list) for v in data.values()):
                # Validate entries are strings
                if all(all(isinstance(x, str) for x in v) for v in data.values()):
                    checks["search_results_json_valid_format"] = True
                    exact_ok = True
                    for k, expected_list in expected_search_map.items():
                        # Must contain exactly the specified single string and no others
                        got_list = data.get(k, [])
                        if len(got_list) != len(expected_list) or set(got_list) != set(expected_list):
                            exact_ok = False
                            break
                    if exact_ok:
                        checks["search_results_json_exact_matches"] = True

    # Check status.txt
    if os.path.isfile(status_txt_path):
        checks["has_status_txt"] = True
        text = load_text(status_txt_path) or ""
        if "Version: 2.0.0" in text:
            checks["status_contains_version"] = True
        if "Data: output/data_store" in text:
            checks["status_contains_data_dir"] = True
        if "Status: ready" in text:
            checks["status_contains_ready"] = True

    # Compute reward: 4 groups, each all-or-nothing, equal weight
    export_group_pass = checks["has_cli_export_file"] and checks["cli_export_contains_expected_entries"]
    entries_group_pass = checks["has_entries_json"] and checks["entries_json_contains_exact_entries"]
    search_group_pass = checks["has_search_results_json"] and checks["search_results_json_exact_matches"]
    status_group_pass = checks["has_status_txt"] and checks["status_contains_version"] and checks["status_contains_data_dir"] and checks["status_contains_ready"]

    reward = 0.0
    total_groups = 4
    passed_groups = sum([export_group_pass, entries_group_pass, search_group_pass, status_group_pass])
    reward = passed_groups / total_groups

    # Print single JSON object
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()