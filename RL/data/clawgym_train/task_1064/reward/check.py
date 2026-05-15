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

def is_text_ext(path):
    allowed_exts = {".txt", ".csv", ".json", ".jsonl", ".md", ".tsv", ".yaml", ".yml", ".xml", ".html", ".py"}
    _, ext = os.path.splitext(path)
    return ext.lower() in allowed_exts

def walk_output_files(output_dir):
    for root, dirs, files in os.walk(output_dir):
        for name in files:
            path = os.path.join(root, name)
            if is_text_ext(path):
                yield path

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # Presence checks
        "has_src_app": False,
        "has_data_tasks": False,
        "has_report": False,
        "has_task_tree": False,
        "has_tests": False,

        # app.py content checks
        "app_has_functions": False,
        "app_has_entrypoint": False,
        "app_has_commands": False,
        "app_no_TODO_FIXME": False,

        # TASK_TREE.json checks
        "task_tree_valid_json": False,
        "task_tree_array_len": False,
        "task_tree_nodes_schema": False,
        "task_tree_no_delete": False,
        "task_tree_status_all_verified": False,

        # REPORT.md checks
        "report_has_sections": False,
        "report_has_done_verified_token": False,
        "report_has_zero_todo_statement": False,

        # tests content
        "tests_have_functions": False,

        # data/tasks.json checks
        "data_valid_json": False,
        "data_has_true_and_false": False,
        "data_all_have_id_and_title": False,

        # Global rule
        "output_global_no_TODO_FIXME": False,
    }

    # Expected output paths
    app_path = os.path.join(output_dir, "src", "app.py")
    data_path = os.path.join(output_dir, "data", "tasks.json")
    report_path = os.path.join(output_dir, "REPORT.md")
    task_tree_path = os.path.join(output_dir, "TASK_TREE.json")
    tests_path = os.path.join(output_dir, "tests", "test_app.py")

    # Presence
    if os.path.isfile(app_path):
        checks["has_src_app"] = True
    if os.path.isfile(data_path):
        checks["has_data_tasks"] = True
    if os.path.isfile(report_path):
        checks["has_report"] = True
    if os.path.isfile(task_tree_path):
        checks["has_task_tree"] = True
    if os.path.isfile(tests_path):
        checks["has_tests"] = True

    # app.py content checks
    app_src = read_text(app_path) if checks["has_src_app"] else None
    if app_src is not None:
        # Must contain function definitions
        funcs_needed = [
            "def load_tasks(",
            "def save_tasks(",
            "def mark_complete(",
            "def status_summary(",
        ]
        if all(f in app_src for f in funcs_needed):
            checks["app_has_functions"] = True

        # Entry point marker (accept single or double quotes)
        if ("if __name__ == '__main__':" in app_src) or ('if __name__ == "__main__":' in app_src):
            checks["app_has_entrypoint"] = True

        # Commands presence (list, filter, complete, summary) - regex word boundary search
        lower_src = app_src.lower()
        needed_cmds = ["list", "filter", "complete", "summary"]
        if all(re.search(r"\b" + re.escape(cmd) + r"\b", lower_src) for cmd in needed_cmds):
            checks["app_has_commands"] = True

        # No 'TODO' or 'FIXME' substrings (case-sensitive, as specified)
        if ("TODO" not in app_src) and ("FIXME" not in app_src):
            checks["app_no_TODO_FIXME"] = True

    # TASK_TREE.json checks
    task_tree = None
    if checks["has_task_tree"]:
        raw = read_text(task_tree_path)
        if raw is not None:
            try:
                task_tree = json.loads(raw)
                checks["task_tree_valid_json"] = isinstance(task_tree, list)
                if isinstance(task_tree, list) and len(task_tree) >= 5:
                    checks["task_tree_array_len"] = True

                if isinstance(task_tree, list):
                    schema_ok = True
                    no_delete = True
                    status_all_verified = True
                    allowed_types = {"READ", "ADD", "EDIT", "VERIFY"}
                    for node in task_tree:
                        # Node must be dict with required keys
                        if not isinstance(node, dict):
                            schema_ok = False
                            break
                        if not all(k in node for k in ("id", "title", "type", "status")):
                            schema_ok = False
                            break
                        # id: str or int
                        if not isinstance(node["id"], (str, int)):
                            schema_ok = False
                            break
                        # title: string
                        if not isinstance(node["title"], str):
                            schema_ok = False
                            break
                        # type: allowed
                        if node["type"] not in allowed_types:
                            if node["type"] == "DELETE":
                                no_delete = False
                            schema_ok = False
                            break
                        # status: string and exact token match
                        if not isinstance(node["status"], str):
                            schema_ok = False
                            break
                        if node["status"] != "[DONE — VERIFIED]":
                            status_all_verified = False
                    if schema_ok:
                        checks["task_tree_nodes_schema"] = True
                    if no_delete:
                        checks["task_tree_no_delete"] = True
                    if status_all_verified:
                        checks["task_tree_status_all_verified"] = True
            except Exception:
                # parsing failed: leave task_tree checks as False
                pass

    # REPORT.md checks
    report_txt = read_text(report_path) if checks["has_report"] else None
    if report_txt is not None:
        low = report_txt.lower()
        # Sections: "Task Tree", "Completion", "Code Read-Back" (accept "code read back" too)
        has_task_tree_section = "task tree" in low
        has_completion_section = "completion" in low
        has_code_readback_section = ("code read-back" in low) or ("code read back" in low)
        if has_task_tree_section and has_completion_section and has_code_readback_section:
            checks["report_has_sections"] = True

        # Must include at least one occurrence of exact token "[DONE — VERIFIED]"
        if "[DONE — VERIFIED]" in report_txt:
            checks["report_has_done_verified_token"] = True

        # Explicit statement that there are zero TODO/FIXME items
        # Heuristic: presence of "todo" or "fixme" and a negation term ("zero" / "no" / "none" / "0")
        neg_terms = ["zero", "no ", " none", " 0 "]
        has_todo_or_fixme = ("todo" in low) or ("fixme" in low)
        has_negation = any(term in low for term in neg_terms)
        if has_todo_or_fixme and has_negation:
            checks["report_has_zero_todo_statement"] = True

    # tests content
    tests_txt = read_text(tests_path) if checks["has_tests"] else None
    if tests_txt is not None:
        if ("def test_mark_complete" in tests_txt) and ("def test_status_summary" in tests_txt):
            checks["tests_have_functions"] = True

    # data/tasks.json checks
    data_ok = False
    data_array = None
    if checks["has_data_tasks"]:
        data_raw = read_text(data_path)
        if data_raw is not None:
            try:
                data_array = json.loads(data_raw)
                data_ok = isinstance(data_array, list)
                if data_ok:
                    checks["data_valid_json"] = True

                    # Each task must have 'id' and 'title'
                    all_have_fields = True
                    has_true = False
                    has_false = False
                    for item in data_array:
                        if not isinstance(item, dict):
                            all_have_fields = False
                            break
                        if "id" not in item or "title" not in item:
                            all_have_fields = False
                            break
                        # title must be string; id can be str or int
                        if not isinstance(item["title"], str):
                            all_have_fields = False
                            break
                        if not isinstance(item.get("id"), (str, int)):
                            all_have_fields = False
                            break
                        # done presence
                        if "done" in item and isinstance(item["done"], bool):
                            if item["done"] is True:
                                has_true = True
                            if item["done"] is False:
                                has_false = True
                    if all_have_fields:
                        checks["data_all_have_id_and_title"] = True
                    if has_true and has_false:
                        checks["data_has_true_and_false"] = True
            except Exception:
                pass

    # Global no-TODO or FIXME across output/ (case-sensitive for uppercase tokens)
    global_ok = True
    if os.path.isdir(output_dir):
        for fpath in walk_output_files(output_dir):
            txt = read_text(fpath)
            if txt is None:
                continue
            if ("TODO" in txt) or ("FIXME" in txt):
                global_ok = False
                break
        checks["output_global_no_TODO_FIXME"] = global_ok
    else:
        checks["output_global_no_TODO_FIXME"] = False

    # Compute reward
    # Count only artifact-dependent checks. If no checks passed at all, reward is 0.0
    check_items = list(checks.items())
    total = len(check_items)
    passed = sum(1 for _, v in check_items if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total

    # Ensure strict no-op baseline: if output dir missing or none of the required files exist, reward = 0.0
    required_presence = ["has_src_app", "has_data_tasks", "has_report", "has_task_tree", "has_tests"]
    if not os.path.isdir(output_dir) or not any(checks[k] for k in required_presence):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()