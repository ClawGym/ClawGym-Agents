import os
import sys
import json
import re
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    txt = read_text(path)
    if txt is None:
        return None
    return [line.rstrip("\n") for line in txt.splitlines()]

def find_command_by_export_path(lines, export_path):
    # Return the first command line that mentions the specific export CSV path
    for line in lines:
        if export_path in line:
            return line
    return None

def header_equals(path, expected_header):
    try:
        with open(path, "r", encoding="utf-8") as f:
            first = f.readline().rstrip("\n").rstrip("\r")
            return first == expected_header
    except Exception:
        return False

def csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None

def load_sample_paths(sample_paths_file):
    sample_set = set()
    lines = read_lines(sample_paths_file)
    if lines is None:
        return sample_set
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        sample_set.add(stripped)
    return sample_set

def ensure_dirs_for_exports(paths):
    # Not used in checker; kept for clarity if needed
    for p in paths:
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    commands_path = os.path.join(output_dir, "commands.txt")
    run_script_path = os.path.join(output_dir, "run_searches.py")
    readme_path = os.path.join(output_dir, "README.md")

    samples_recent_path = os.path.join(output_dir, "samples", "recent_docs.csv")
    samples_node_modules_path = os.path.join(output_dir, "samples", "node_modules.csv")
    samples_heavy_path = os.path.join(output_dir, "samples", "heavy_archives.csv")

    sample_paths_file = os.path.join(input_dir, "sample_paths.txt")

    # 1) commands.txt checks
    checks["commands_file_exists"] = os.path.isfile(commands_path)
    commands_lines = read_lines(commands_path) if checks["commands_file_exists"] else None
    nonempty_lines = []
    if commands_lines is not None:
        nonempty_lines = [ln for ln in commands_lines if ln.strip() != ""]
    checks["commands_min_lines"] = bool(nonempty_lines) and len(nonempty_lines) >= 3

    # All lines start with "es " and no absolute drive paths
    def starts_with_es(line):
        return line.lstrip().startswith("es ")
    def has_abs_drive_path(line):
        # Detect Windows drive pattern like C:\ or D:\ in the line
        return re.search(r"\b[A-Za-z]:\\", line) is not None

    if checks["commands_min_lines"]:
        checks["commands_all_start_es"] = all(starts_with_es(ln) for ln in nonempty_lines)
        checks["commands_no_abs_drive_paths"] = not any(has_abs_drive_path(ln) for ln in nonempty_lines)
        # All commands must include -path input/... and -export-csv output/...
        checks["commands_all_have_path_input"] = all(re.search(r"-path\s+\"?input/[^\"\s]*\"?", ln) for ln in nonempty_lines)
        checks["commands_all_have_export_output"] = all(re.search(r"-export-csv\s+\"?output/[^\"\s]*\"?", ln) for ln in nonempty_lines)
    else:
        checks["commands_all_start_es"] = False
        checks["commands_no_abs_drive_paths"] = False
        checks["commands_all_have_path_input"] = False
        checks["commands_all_have_export_output"] = False

    # Specific task command checks
    # a) recent_docs
    recent_export = "output/reports/recent_docs.csv"
    node_modules_export = "output/reports/node_modules.csv"
    heavy_export = "output/reports/heavy_archives.csv"

    recent_cmd = None
    node_modules_cmd = None
    heavy_cmd = None
    if nonempty_lines:
        recent_cmd = find_command_by_export_path(nonempty_lines, recent_export)
        node_modules_cmd = find_command_by_export_path(nonempty_lines, node_modules_export)
        heavy_cmd = find_command_by_export_path(nonempty_lines, heavy_export)

    checks["cmd_recent_docs_present"] = recent_cmd is not None
    checks["cmd_node_modules_present"] = node_modules_cmd is not None
    checks["cmd_heavy_archives_present"] = heavy_cmd is not None

    # Normalize for case-insensitive flag/option detection (Everything flags are lowercase in examples)
    def lc(s):
        return s.lower() if s is not None else ""

    # recent_docs requirements
    rc = lc(recent_cmd)
    checks["cmd_recent_docs_pattern_docx"] = "*.docx" in rc or ".docx" in rc
    checks["cmd_recent_docs_path_scope"] = "-path" in rc and "input/snapshots/docs" in rc
    checks["cmd_recent_docs_sort_date"] = "-sort -date-modified" in rc
    checks["cmd_recent_docs_limit_15"] = "-n 15" in rc
    checks["cmd_recent_docs_columns"] = all(tok in rc for tok in ["-name", "-size", "-date-modified", "-path"])
    checks["cmd_recent_docs_export_path"] = recent_cmd is not None and recent_export in recent_cmd

    # node_modules requirements
    nc = lc(node_modules_cmd)
    checks["cmd_node_modules_term"] = "node_modules" in nc
    checks["cmd_node_modules_path_scope"] = "-path" in nc and "input/snapshots/projects" in nc
    checks["cmd_node_modules_dir_only"] = "/ad" in nc
    checks["cmd_node_modules_limit_200"] = "-n 200" in nc
    # Columns include -name -date-modified -path (size not required)
    checks["cmd_node_modules_columns"] = all(tok in nc for tok in ["-name", "-date-modified", "-path"])
    checks["cmd_node_modules_export_path"] = node_modules_cmd is not None and node_modules_export in node_modules_cmd

    # heavy_archives requirements
    hc = lc(heavy_cmd)
    checks["cmd_heavy_archives_pattern_zip"] = "*.zip" in hc or ".zip" in hc
    checks["cmd_heavy_archives_path_scope"] = "-path" in hc and "input/snapshots" in hc
    checks["cmd_heavy_archives_files_only"] = "/a-d" in hc
    checks["cmd_heavy_archives_sort_size"] = "-sort -size" in hc
    checks["cmd_heavy_archives_limit_100"] = "-n 100" in hc
    checks["cmd_heavy_archives_columns"] = all(tok in hc for tok in ["-name", "-size", "-date-modified", "-path"])
    checks["cmd_heavy_archives_export_path"] = heavy_cmd is not None and heavy_export in heavy_cmd

    # 2) run_searches.py checks
    checks["runner_exists"] = os.path.isfile(run_script_path)
    run_txt = read_text(run_script_path) if checks["runner_exists"] else None
    if run_txt is None:
        checks["runner_imports_subprocess"] = False
        checks["runner_creates_dirs"] = False
        checks["runner_references_csvs"] = False
        checks["runner_has_es_literal"] = False
    else:
        low = run_txt.lower()
        checks["runner_imports_subprocess"] = ("import subprocess" in low) or ("from subprocess import" in low)
        # Directory creation: look for os.makedirs(..., exist_ok=True) or Path(...).mkdir(parents=True, exist_ok=True)
        creates_dirs = False
        if "makedirs(" in low and "exist_ok=True" in low:
            creates_dirs = True
        if ".mkdir(" in low and "parents=True" in low and "exist_ok=True" in low:
            creates_dirs = True
        checks["runner_creates_dirs"] = creates_dirs
        # References the three CSV export paths
        refs = (recent_export in run_txt) and (node_modules_export in run_txt) and (heavy_export in run_txt)
        checks["runner_references_csvs"] = refs
        checks["runner_has_es_literal"] = ("es " in run_txt)

    # 3) README.md checks
    checks["readme_exists"] = os.path.isfile(readme_path)
    readme_txt = read_text(readme_path) if checks["readme_exists"] else None
    if readme_txt is None:
        checks["readme_mentions_recent_docs"] = False
        checks["readme_mentions_node_modules"] = False
        checks["readme_mentions_heavy_archives"] = False
    else:
        rt = readme_txt
        checks["readme_mentions_recent_docs"] = ("recent_docs" in rt and recent_export in rt)
        checks["readme_mentions_node_modules"] = ("node_modules" in rt and node_modules_export in rt)
        checks["readme_mentions_heavy_archives"] = ("heavy_archives" in rt and heavy_export in rt)

    # 4) Sample CSVs checks
    # Load allowed paths from input/sample_paths.txt
    sample_set = load_sample_paths(sample_paths_file)

    # Helper to check CSV
    def check_csv_samples(csv_path, expected_header, path_predicate):
        exists = os.path.isfile(csv_path)
        header_ok = False
        min_rows = False
        paths_from_sample = False
        paths_pattern_ok = False

        if exists:
            header_ok = header_equals(csv_path, expected_header)
            rows = csv_rows(csv_path)
            if rows and len(rows) >= 3:  # header + at least 2 rows
                min_rows = True
                # Determine column index of Path
                header = rows[0]
                # If using csv reader, header is list; reconstruct expected to ensure index
                # We'll find "Path" column
                try:
                    path_idx = header.index("Path")
                except ValueError:
                    path_idx = -1
                if path_idx >= 0:
                    all_in_sample = True
                    all_pattern_ok = True
                    for row in rows[1:]:
                        if not row or len(row) <= path_idx:
                            all_in_sample = False
                            all_pattern_ok = False
                            break
                        p = row[path_idx].strip()
                        # Check is in sample paths set
                        if p not in sample_set:
                            all_in_sample = False
                        if not path_predicate(p):
                            all_pattern_ok = False
                    paths_from_sample = all_in_sample
                    paths_pattern_ok = all_pattern_ok
                else:
                    paths_from_sample = False
                    paths_pattern_ok = False
            else:
                min_rows = False
        return exists, header_ok, min_rows, paths_from_sample, paths_pattern_ok

    # Predicates for each CSV
    def pred_recent(p):
        return p.startswith("input/snapshots/docs/") and p.lower().endswith(".docx")

    def pred_node_modules(p):
        if not p.startswith("input/snapshots/projects/"):
            return False
        parts = [seg for seg in p.strip("/").split("/")]
        return "node_modules" in parts

    def pred_heavy(p):
        return p.startswith("input/snapshots/") and p.lower().endswith(".zip")

    # recent_docs
    r_exists, r_header_ok, r_min_rows, r_in_sample, r_pattern_ok = check_csv_samples(
        samples_recent_path, "Name,Size,Date Modified,Path", pred_recent
    )
    checks["sample_recent_exists"] = r_exists
    checks["sample_recent_header_ok"] = r_header_ok
    checks["sample_recent_min_rows"] = r_min_rows
    checks["sample_recent_paths_from_sample"] = r_in_sample
    checks["sample_recent_paths_pattern_ok"] = r_pattern_ok

    # node_modules
    n_exists, n_header_ok, n_min_rows, n_in_sample, n_pattern_ok = check_csv_samples(
        samples_node_modules_path, "Name,Date Modified,Path", pred_node_modules
    )
    checks["sample_node_modules_exists"] = n_exists
    checks["sample_node_modules_header_ok"] = n_header_ok
    checks["sample_node_modules_min_rows"] = n_min_rows
    checks["sample_node_modules_paths_from_sample"] = n_in_sample
    checks["sample_node_modules_paths_pattern_ok"] = n_pattern_ok

    # heavy_archives
    h_exists, h_header_ok, h_min_rows, h_in_sample, h_pattern_ok = check_csv_samples(
        samples_heavy_path, "Name,Size,Date Modified,Path", pred_heavy
    )
    checks["sample_heavy_exists"] = h_exists
    checks["sample_heavy_header_ok"] = h_header_ok
    checks["sample_heavy_min_rows"] = h_min_rows
    checks["sample_heavy_paths_from_sample"] = h_in_sample
    checks["sample_heavy_paths_pattern_ok"] = h_pattern_ok

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure no-op baseline yields 0.0: if output dir is missing or empty
    # If all key files missing, passed will be 0, keeping reward 0.0 already.
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()