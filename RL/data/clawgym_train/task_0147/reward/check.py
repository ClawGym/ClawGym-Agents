import json
import os
import re
import sys
import subprocess
import csv
from datetime import datetime, timezone
from typing import List, Dict, Any

def get_workspace_root() -> str:
    if len(sys.argv) > 1 and sys.argv[1]:
        return sys.argv[1]
    return "/root/.openclaw/workspace"

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

def file_exists(path: str) -> bool:
    try:
        return os.path.isfile(path)
    except Exception:
        return False

def dir_exists(path: str) -> bool:
    try:
        return os.path.isdir(path)
    except Exception:
        return False

def compile_expected_from_csv(csv_path: str) -> List[Dict[str, Any]]:
    # Build expected JSON according to spec:
    # - First non-blank row is headers
    # - Ignore blank/whitespace-only lines
    # - Trim cell whitespace
    # - Numeric-looking to numbers (int/float)
    # - Case-insensitive "null" to None
    # - Missing cells as None
    try:
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()
    except Exception:
        return []
    filtered = [ln for ln in lines if ln.strip() != ""]
    if not filtered:
        return []
    # Parse with csv.reader to respect quotes; trim whitespace manually after parsing
    reader = csv.reader(filtered)
    rows = list(reader)
    if not rows:
        return []
    # Trim headers
    headers = [h.strip() for h in rows[0]]
    # Numeric detection regex
    int_re = re.compile(r"^[+-]?\d+$")
    float_re = re.compile(r"^[+-]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][+-]?\d+)?$")
    def convert(cell: str):
        if cell is None:
            return None
        s = cell.strip()
        if s == "":
            return None
        if s.lower() == "null":
            return None
        if int_re.match(s):
            try:
                return int(s)
            except Exception:
                pass
        if float_re.match(s) and not int_re.match(s):
            try:
                return float(s)
            except Exception:
                pass
        # Also allow floats like "1.0" where both regexes may match; ensure float if decimal point or exponent present
        if (("." in s) or ("e" in s.lower())) and float_re.match(s):
            try:
                return float(s)
            except Exception:
                pass
        return s
    expected: List[Dict[str, Any]] = []
    for row in rows[1:]:
        # Ensure length at least headers
        values = list(row)
        # Trim and convert each
        converted = []
        for i in range(len(headers)):
            val = values[i] if i < len(values) else None
            if val is None:
                converted.append(None)
            else:
                converted.append(convert(val))
        # Build dict
        obj = {}
        for i, key in enumerate(headers):
            obj[key] = converted[i] if i < len(converted) else None
        expected.append(obj)
    return expected

def json_load(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def run_python(cmd: list, cwd: str) -> (int, str, str):
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return 127, "", str(e)

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "todo_file_present": False,
        "todo_has_checkbox_and_phrases": False,
        "lessons_file_present_with_metadata": False,
        "errors_file_present_with_sections": False,
        "feature_request_present_with_fields": False,
        "memory_log_present": False,
        "tool_script_present": False,
        "cli_exec_ok": False,
        "artifact_json_valid_list": False,
        "artifact_matches_expected": False,
        "tests_run_ok": False,
    }

    # Paths
    todo_path = os.path.join(output_dir, "tasks", "todo.md")
    lessons_path = os.path.join(output_dir, "tasks", "lessons.md")
    errors_path = os.path.join(output_dir, "tasks", "errors.md")
    feats_path = os.path.join(output_dir, "tasks", "feature_requests.md")
    memory_dir = os.path.join(output_dir, "memory")
    tool_path = os.path.join(output_dir, "tools", "csv_to_json.py")
    tests_path = os.path.join(output_dir, "tests", "test_csv_to_json.py")
    input_csv = os.path.join(input_dir, "data.csv")
    artifact_path = os.path.join(output_dir, "artifacts", "data.json")

    # Early baseline: if output/ missing or empty, reward must be 0.0
    output_exists = dir_exists(output_dir)
    if not output_exists:
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # 1) Planning & logs validations
    if file_exists(todo_path):
        checks["todo_file_present"] = True
        todo_txt = read_text(todo_path)
        has_checkbox = ("- [ ]" in todo_txt) or ("- [x]" in todo_txt) or ("- [X]" in todo_txt)
        has_verification = ("Verification Before Done" in todo_txt)
        has_elegance = ("Demand Elegance" in todo_txt)
        has_sub_or_parallel = ("Subagent" in todo_txt) or ("parallel" in todo_txt) or ("Parallel" in todo_txt)
        if has_checkbox and has_verification and has_elegance and has_sub_or_parallel:
            checks["todo_has_checkbox_and_phrases"] = True

    if file_exists(lessons_path):
        lessons_txt = read_text(lessons_path)
        # ID pattern and required fields
        lrn_id = re.search(r"\[LRN-\d{8}-\d{3}\]", lessons_txt) is not None
        fields = all(k in lessons_txt for k in ["Priority:", "Status:", "Area:", "Pattern-Key:", "Recurrence-Count:"])
        src_or_tags = ("Source:" in lessons_txt) or ("Tags:" in lessons_txt)
        if lrn_id and fields and src_or_tags:
            checks["lessons_file_present_with_metadata"] = True

    if file_exists(errors_path):
        err_txt = read_text(errors_path)
        err_id = re.search(r"\[ERR-\d{8}-\d{3}\]", err_txt) is not None
        sections = all(s in err_txt for s in ["Error Output:", "Context:", "Suggested Fix:", "Repro Steps:", "Severity:"])
        if err_id and sections:
            checks["errors_file_present_with_sections"] = True

    if file_exists(feats_path):
        feat_txt = read_text(feats_path)
        feat_id = re.search(r"\[FEAT-\d{8}-\d{3}\]", feat_txt) is not None
        complexity = ("Complexity" in feat_txt) or ("Complexity Estimate" in feat_txt)
        suggested_impl = ("Suggested Implementation" in feat_txt)
        if feat_id and complexity and suggested_impl:
            checks["feature_request_present_with_fields"] = True

    mem_ok = False
    if dir_exists(memory_dir):
        try:
            for root, _dirs, files in os.walk(memory_dir):
                for fn in files:
                    if re.match(r"\d{4}-\d{2}-\d{2}\.md$", fn):
                        fp = os.path.join(root, fn)
                        txt = read_text(fp)
                        if ("Session" in txt) or ("session" in txt) or ("log" in txt) or ("Log" in txt):
                            mem_ok = True
                            break
                if mem_ok:
                    break
        except Exception:
            mem_ok = False
    if mem_ok:
        checks["memory_log_present"] = True

    # 2) Code & tests
    if file_exists(tool_path):
        checks["tool_script_present"] = True
        # Run CLI: python3 output/tools/csv_to_json.py input/data.csv output/artifacts/data.json
        # Ensure parent dir for artifact exists? The task expects the script to handle path; do not create directories here.
        # Execute and capture return code
        rc, _out, _err = run_python(["python3", tool_path, input_csv, artifact_path], cwd=workspace_root)
        if rc == 0 and file_exists(artifact_path):
            checks["cli_exec_ok"] = True

    # Validate artifact JSON after attempting to run CLI
    if file_exists(artifact_path):
        data = json_load(artifact_path)
        if isinstance(data, list) and all(isinstance(x, dict) for x in data):
            checks["artifact_json_valid_list"] = True
            # Build expected from input/data.csv
            expected = compile_expected_from_csv(input_csv)
            # Compare equality; if equal, mark pass
            if expected == data:
                checks["artifact_matches_expected"] = True

    # Run tests
    if file_exists(tests_path):
        rc_t, _out_t, _err_t = run_python(["python3", tests_path], cwd=workspace_root)
        if rc_t == 0:
            checks["tests_run_ok"] = True

    # Compute reward as fraction of passed checks; baseline 0 if no outputs produced
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if nothing present in output (no files found), force 0.0
    # Determine if any artifact-dependent check is true or any file exists
    any_output_files = False
    try:
        for _root, _dirs, files in os.walk(output_dir):
            if files:
                any_output_files = True
                break
    except Exception:
        any_output_files = False
    if not any_output_files:
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()