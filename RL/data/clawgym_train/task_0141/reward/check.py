import json
import os
import sys
import csv

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            return list(reader)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used

    checks = {
        # Recent files CSV validations
        "recent_files_exists": False,
        "recent_files_header_ok": False,
        "recent_files_line_count_ok": False,
        "recent_files_has_project_plan_row": False,
        "recent_files_has_readme_row": False,
        "recent_files_has_design_spec_row": False,

        # Programs JSON validations
        "programs_exists": False,
        "programs_is_array_len5": False,
        "programs_elements_keys_exact": False,
        "programs_sorted_by_name": False,
        "programs_first_is_google_chrome": False,
        "programs_last_is_zoom": False,

        # Metrics summary JSON validations
        "metrics_exists": False,
        "metrics_json_object": False,
        "metrics_keys_exact": False,
        "metrics_recent_files_count_5": False,
        "metrics_running_processes_count_6": False,
        "metrics_installed_programs_count_5": False,
        "metrics_unique_extensions_4": False,
        "metrics_by_extension_counts_exact": False,
        "metrics_top_processes_len3": False,
        "metrics_top_processes_exact_entries": False,

        # Processes not installed JSON validations
        "processes_not_installed_exists": False,
        "processes_not_installed_is_array": False,
        "processes_not_installed_sorted": False,
        "processes_not_installed_exact_entries": False,
    }

    # Paths
    recent_files_csv_path = os.path.join(output_dir, "normalized", "recent_files.csv")
    programs_json_path = os.path.join(output_dir, "normalized", "programs.json")
    metrics_summary_path = os.path.join(output_dir, "metrics", "summary.json")
    processes_not_installed_path = os.path.join(output_dir, "checks", "processes_not_installed.json")

    # 1) Check recent_files.csv
    if os.path.isfile(recent_files_csv_path):
        checks["recent_files_exists"] = True
        lines = read_text_lines(recent_files_csv_path)
        if lines is not None and len(lines) >= 1:
            header = lines[0]
            if header == "filename,path,type,last_edited_iso":
                checks["recent_files_header_ok"] = True
            if len(lines) == 6:
                checks["recent_files_line_count_ok"] = True

            # Parse CSV rows robustly (to handle quoted fields)
            rows = parse_csv_rows(recent_files_csv_path)
            if rows and len(rows) >= 2:
                # Expect header row then data rows
                data_rows = rows[1:]
                # Normalize to length-4 rows if possible
                def safe_get(row, idx):
                    try:
                        return row[idx]
                    except Exception:
                        return None

                for row in data_rows:
                    fn = safe_get(row, 0)
                    last_iso = safe_get(row, 3)
                    if fn == "project_plan.md" and last_iso == "2026-04-10T13:20:05":
                        checks["recent_files_has_project_plan_row"] = True
                    if fn == "README" and last_iso == "2026-04-08T17:01:00":
                        checks["recent_files_has_readme_row"] = True
                    if fn == "design_spec.md" and last_iso == "2026-04-11T09:05:30":
                        checks["recent_files_has_design_spec_row"] = True

    # 2) Check programs.json
    if os.path.isfile(programs_json_path):
        checks["programs_exists"] = True
        programs = load_json_file(programs_json_path)
        if isinstance(programs, list):
            if len(programs) == 5:
                checks["programs_is_array_len5"] = True
            # keys exact for each element
            expected_keys = {"name", "publisher", "version", "install_location"}
            keys_ok = True
            names = []
            for el in programs:
                if not isinstance(el, dict):
                    keys_ok = False
                    break
                if set(el.keys()) != expected_keys:
                    keys_ok = False
                    break
                # collect names
                names.append(el.get("name"))
            if keys_ok and len(names) == len(programs):
                checks["programs_elements_keys_exact"] = True
                # sorted by name ascending
                if names == sorted(names):
                    checks["programs_sorted_by_name"] = True
                # first and last element names
                if len(names) >= 1:
                    if names[0] == "Google Chrome":
                        checks["programs_first_is_google_chrome"] = True
                    if names[-1] == "Zoom":
                        checks["programs_last_is_zoom"] = True

    # 3) Check metrics/summary.json
    if os.path.isfile(metrics_summary_path):
        checks["metrics_exists"] = True
        summary = load_json_file(metrics_summary_path)
        if isinstance(summary, dict):
            checks["metrics_json_object"] = True
            required_keys = {
                "recent_files_count",
                "unique_extensions",
                "by_extension",
                "running_processes_count",
                "installed_programs_count",
                "top_processes",
            }
            if set(summary.keys()) == required_keys:
                checks["metrics_keys_exact"] = True

            # Validate counts
            if summary.get("recent_files_count") == 5:
                checks["metrics_recent_files_count_5"] = True
            if summary.get("running_processes_count") == 6:
                checks["metrics_running_processes_count_6"] = True
            if summary.get("installed_programs_count") == 5:
                checks["metrics_installed_programs_count_5"] = True
            if summary.get("unique_extensions") == 4:
                checks["metrics_unique_extensions_4"] = True

            # Validate by_extension mapping
            expected_by_ext = {"md": 2, "xlsx": 1, "txt": 1, "": 1}
            by_ext = summary.get("by_extension")
            if isinstance(by_ext, dict) and by_ext == expected_by_ext:
                checks["metrics_by_extension_counts_exact"] = True

            # Validate top_processes
            expected_top = [
                {"pid": 1605, "name": "ffmpeg", "cpu": 42.3},
                {"pid": 1504, "name": "python3", "cpu": 35.0},
                {"pid": 1302, "name": "Code", "cpu": 22.7},
            ]
            tp = summary.get("top_processes")
            if isinstance(tp, list) and len(tp) == 3:
                checks["metrics_top_processes_len3"] = True
                # Check each entry has correct types and values
                def is_number(x):
                    return isinstance(x, (int, float))
                all_match = True
                for idx, exp in enumerate(expected_top):
                    try:
                        item = tp[idx]
                        if not isinstance(item, dict):
                            all_match = False
                            break
                        # exact keys (pid, name, cpu)
                        if set(item.keys()) != {"pid", "name", "cpu"}:
                            all_match = False
                            break
                        pid_ok = isinstance(item.get("pid"), int) or (is_number(item.get("pid")) and int(item.get("pid")) == exp["pid"])
                        name_ok = isinstance(item.get("name"), str) and item.get("name") == exp["name"]
                        cpu_val = item.get("cpu")
                        cpu_type_ok = is_number(cpu_val)
                        cpu_ok = cpu_type_ok and abs(float(cpu_val) - float(exp["cpu"])) < 1e-9
                        if not (pid_ok and name_ok and cpu_ok):
                            all_match = False
                            break
                    except Exception:
                        all_match = False
                        break
                if all_match:
                    checks["metrics_top_processes_exact_entries"] = True

    # 4) Check processes_not_installed.json
    if os.path.isfile(processes_not_installed_path):
        checks["processes_not_installed_exists"] = True
        arr = load_json_file(processes_not_installed_path)
        if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
            checks["processes_not_installed_is_array"] = True
            if arr == sorted(arr):
                checks["processes_not_installed_sorted"] = True
            expected_list = ["Code", "backupd", "chrome", "ffmpeg", "python3"]
            if arr == expected_list:
                checks["processes_not_installed_exact_entries"] = True

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output dir missing or empty and nothing passed, reward is 0.0 automatically
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()