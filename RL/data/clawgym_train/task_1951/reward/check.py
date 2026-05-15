import json
import os
import sys

def read_text_lines(path):
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

    reports_dir = os.path.join(output_dir, "reports")
    todo_path = os.path.join(reports_dir, "todo_report.json")
    routes_path = os.path.join(reports_dir, "routes.csv")
    import_index_path = os.path.join(reports_dir, "import_index.txt")
    summary_md_path = os.path.join(reports_dir, "summary.md")

    checks = {
        "has_todo_report": False,
        "todo_is_json_array": False,
        "todo_schema_valid": False,
        "todo_exact_match": False,

        "has_routes_csv": False,
        "routes_header_ok": False,
        "routes_rows_ok": False,

        "has_import_index": False,
        "import_lines_ok": False,

        "has_summary_md": False,
        "summary_exact_ok": False,
    }

    # 1) Validate todo_report.json
    if os.path.isfile(todo_path):
        checks["has_todo_report"] = True
        try:
            with open(todo_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                checks["todo_is_json_array"] = True
                # schema validation
                schema_ok = True
                tuples = []
                for item in data:
                    if not isinstance(item, dict):
                        schema_ok = False
                        break
                    if set(item.keys()) != {"path", "line", "text"}:
                        schema_ok = False
                        break
                    if not isinstance(item["path"], str):
                        schema_ok = False
                        break
                    if not isinstance(item["line"], int):
                        schema_ok = False
                        break
                    if not isinstance(item["text"], str):
                        schema_ok = False
                        break
                    tuples.append((item["path"], item["line"], item["text"]))
                if schema_ok:
                    checks["todo_schema_valid"] = True
                    expected = {
                        ("app/main.py", 4, "refactor main entry initialization"),
                        ("app/main.py", 12, "health check implementation"),
                        ("app/utils.py", 4, "consolidate env parsing"),
                        ("scripts/ci.py", 2, "integrate lint step"),
                        ("tests/test_utils.py", 1, "add negative tests"),
                        ("docs/guide.md", 1, "fill me in."),
                    }
                    tuples_set = set(tuples)
                    # Must match exactly and length exactly (prevents duplicates)
                    if tuples_set == expected and len(tuples) == len(expected):
                        checks["todo_exact_match"] = True
        except Exception:
            pass

    # 2) Validate routes.csv
    if os.path.isfile(routes_path):
        checks["has_routes_csv"] = True
        lines = read_text_lines(routes_path)
        if isinstance(lines, list) and len(lines) >= 1:
            header_ok = (lines[0] == "route_path,function_name")
            checks["routes_header_ok"] = header_ok
            data_lines = lines[1:]
            # No extra blank lines allowed; splitlines() will not include trailing blank line unless present in content.
            expected_rows = {"/,index", "/health,health"}
            # Must be exactly two rows, order-independent, no extras
            if len(data_lines) == 2 and set(data_lines) == expected_rows:
                checks["routes_rows_ok"] = True

    # 3) Validate import_index.txt
    if os.path.isfile(import_index_path):
        checks["has_import_index"] = True
        lines = read_text_lines(import_index_path)
        if isinstance(lines, list):
            # consider non-empty, trimmed lines as specified
            trimmed = [ln.strip() for ln in lines if ln.strip() != ""]
            expected_ordered = ["app/main.py", "app/utils.py", "tests/test_utils.py"]
            if trimmed == expected_ordered:
                checks["import_lines_ok"] = True

    # 4) Validate summary.md
    if os.path.isfile(summary_md_path):
        checks["has_summary_md"] = True
        lines = read_text_lines(summary_md_path)
        if isinstance(lines, list):
            expected_summary = ["Total TODOs: 6", "Files with imports: 3", "Discovered routes: 2"]
            if lines == expected_summary:
                checks["summary_exact_ok"] = True

    # Aggregate major artifact checks
    todo_all_ok = checks["has_todo_report"] and checks["todo_is_json_array"] and checks["todo_schema_valid"] and checks["todo_exact_match"]
    routes_all_ok = checks["has_routes_csv"] and checks["routes_header_ok"] and checks["routes_rows_ok"]
    import_all_ok = checks["has_import_index"] and checks["import_lines_ok"]
    summary_all_ok = checks["has_summary_md"] and checks["summary_exact_ok"]

    major_checks = [todo_all_ok, routes_all_ok, import_all_ok, summary_all_ok]
    passed = sum(1 for x in major_checks if x)
    total = len(major_checks)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Ensure numeric between 0 and 1
    reward = float(max(0.0, min(1.0, reward)))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()