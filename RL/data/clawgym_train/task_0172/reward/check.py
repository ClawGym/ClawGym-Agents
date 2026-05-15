import json
import os
import sys
import csv

def load_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            items.append(json.loads(s))
    return items

def parse_simple_yaml_list_of_maps(path):
    # Minimal YAML parser for a top-level list of flat key:value mappings.
    # Supports lines starting with "- " and subsequent indented "key: value" lines.
    items = []
    current = None
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n\r")
            if not line.strip():
                continue
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith("-"):
                # Start a new item
                current = {}
                items.append(current)
                after_dash = stripped[1:].lstrip()
                if after_dash:
                    # Could be "key: value" on the same line
                    if ":" in after_dash:
                        key, val = after_dash.split(":", 1)
                        key = key.strip()
                        val = val.strip()
                        val = strip_quotes(val)
                        current[key] = val
                continue
            # Continuation of current mapping
            if current is None:
                # If file doesn't start with "-", try to parse first mapping anyway
                current = {}
                items.append(current)
            # Expect "key: value"
            if ":" in stripped:
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip()
                val = strip_quotes(val)
                current[key] = val
    # Filter out empty dicts possibly created by malformed content
    items = [d for d in items if isinstance(d, dict) and len(d) > 0]
    return items

def strip_quotes(s):
    if not s:
        return s
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s

def read_csv_with_header(path, delimiter=","):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for r in reader:
            rows.append(r)
    return rows

def ensure_exact_keys(obj, required_keys):
    if not isinstance(obj, dict):
        return False
    return set(obj.keys()) == set(required_keys)

def compute_expected_features(input_path):
    data = load_jsonl(input_path)
    last_by_id = {}
    for item in data:
        if "id" not in item:
            continue
        id_str = str(item.get("id"))
        # Build normalized record
        norm = {
            "id": id_str,
            "title": item.get("title"),
            "status": (str(item.get("status")) if item.get("status") is not None else "").lower(),
            "description": item.get("description"),
            "component": item.get("component"),
        }
        last_by_id[id_str] = norm
    entries = list(last_by_id.values())
    entries.sort(key=lambda x: x["id"])
    return {
        "category": "features",
        "source_files": ["input/features.jsonl"],
        "counts": {"total": len(entries)},
        "entries": entries,
    }

def compute_expected_code_style(input_path):
    items = parse_simple_yaml_list_of_maps(input_path)
    entries = []
    for item in items:
        # Expect keys: id, rule, rationale, severity
        id_str = str(item.get("id"))
        severity = item.get("severity")
        sev_up = str(severity).upper() if severity is not None else ""
        entries.append({
            "id": id_str,
            "rule": item.get("rule"),
            "rationale": item.get("rationale"),
            "severity": sev_up,
        })
    entries.sort(key=lambda x: x["id"])
    return {
        "category": "code_style",
        "source_files": ["input/code_style.yaml"],
        "counts": {"total": len(entries)},
        "entries": entries,
    }

def compute_expected_security(input_path):
    rows = read_csv_with_header(input_path, delimiter=",")
    risk_map = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    last_by_id = {}
    for r in rows:
        rid = r.get("id")
        if rid is None:
            continue
        id_str = str(rid)
        sev = r.get("severity")
        sev_up = str(sev).upper() if sev is not None else ""
        risk = risk_map.get(sev_up, 0)
        norm = {
            "id": id_str,
            "title": r.get("title"),
            "severity": sev_up,
            "status": (str(r.get("status")) if r.get("status") is not None else ""),
            "risk": risk,
        }
        last_by_id[id_str] = norm
    entries = list(last_by_id.values())
    entries.sort(key=lambda x: x["id"])
    return {
        "category": "security",
        "source_files": ["input/security_issues.csv"],
        "counts": {"total": len(entries)},
        "entries": entries,
    }

def compute_expected_ui_styles(input_path):
    with open(input_path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    entries = []
    # Colors
    colors = obj.get("colors", {})
    if isinstance(colors, dict):
        for name, value in colors.items():
            entries.append({
                "type": "color",
                "name": str(name),
                "value": value,
            })
    # Typography
    typo = obj.get("typography", {})
    if isinstance(typo, dict):
        # font_family and base_size
        if "font_family" in typo:
            entries.append({"type": "typography", "name": "font_family", "value": typo.get("font_family")})
        if "base_size" in typo:
            entries.append({"type": "typography", "name": "base_size", "value": typo.get("base_size")})
        # scale array
        scale = typo.get("scale")
        if isinstance(scale, list):
            for idx, val in enumerate(scale):
                entries.append({"type": "typography", "name": f"scale[{idx}]", "value": val})
    # Sort: type then name; "color" before "typography"
    type_order = {"color": 0, "typography": 1}
    entries.sort(key=lambda x: (type_order.get(x.get("type"), 99), str(x.get("name"))))
    return {
        "category": "ui_styles",
        "source_files": ["input/ui_styles.json"],
        "counts": {"total": len(entries)},
        "entries": entries,
    }

def compute_expected_todos(input_path):
    rows = read_csv_with_header(input_path, delimiter="\t")
    last_by_id = {}
    for r in rows:
        rid = r.get("id")
        if rid is None:
            continue
        id_str = str(rid)
        priority = r.get("priority")
        status = r.get("status")
        norm = {
            "id": id_str,
            "task": r.get("task"),
            "assignee": r.get("assignee"),
            "due_date": r.get("due_date"),
            "priority": (str(priority).upper() if priority is not None else ""),
            "status": (str(status).lower() if status is not None else ""),
        }
        last_by_id[id_str] = norm
    entries = list(last_by_id.values())
    entries.sort(key=lambda x: x["id"])
    return {
        "category": "todos",
        "source_files": ["input/todos.tsv"],
        "counts": {"total": len(entries)},
        "entries": entries,
    }

def load_output_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def compare_entries_strict(expected_list, actual_list, required_keys):
    # Ensure list lengths match and each item matches exactly with required keys and no extras
    if not isinstance(actual_list, list):
        return False
    if len(expected_list) != len(actual_list):
        return False
    for exp, act in zip(expected_list, actual_list):
        if not isinstance(act, dict):
            return False
        if set(act.keys()) != set(required_keys):
            return False
        # Compare values for required keys
        for k in required_keys:
            if exp.get(k) != act.get(k):
                return False
    return True

def validate_top_level(obj, expected_category, expected_source_files):
    if not isinstance(obj, dict):
        return False, False, False
    keys_ok = set(obj.keys()) == {"category", "source_files", "counts", "entries"}
    cat_ok = obj.get("category") == expected_category
    sf_ok = obj.get("source_files") == expected_source_files
    return keys_ok, cat_ok, sf_ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    out_project_dir = os.path.join(output_dir, "project")
    feature_out = os.path.join(out_project_dir, "feature-tracker.json")
    code_style_out = os.path.join(out_project_dir, "code-style-tracker.json")
    security_out = os.path.join(out_project_dir, "security-issues.json")
    ui_styles_out = os.path.join(out_project_dir, "ui-styles.json")
    todos_out = os.path.join(out_project_dir, "todolist.json")

    feature_in = os.path.join(input_dir, "features.jsonl")
    code_style_in = os.path.join(input_dir, "code_style.yaml")
    security_in = os.path.join(input_dir, "security_issues.csv")
    ui_styles_in = os.path.join(input_dir, "ui_styles.json")
    todos_in = os.path.join(input_dir, "todos.tsv")

    checks = {
        "feature_file_exists": False,
        "code_style_file_exists": False,
        "security_file_exists": False,
        "ui_styles_file_exists": False,
        "todos_file_exists": False,

        "feature_json_valid": False,
        "code_style_json_valid": False,
        "security_json_valid": False,
        "ui_styles_json_valid": False,
        "todos_json_valid": False,

        "feature_schema_ok": False,
        "code_style_schema_ok": False,
        "security_schema_ok": False,
        "ui_styles_schema_ok": False,
        "todos_schema_ok": False,

        "feature_category_ok": False,
        "code_style_category_ok": False,
        "security_category_ok": False,
        "ui_styles_category_ok": False,
        "todos_category_ok": False,

        "feature_source_files_ok": False,
        "code_style_source_files_ok": False,
        "security_source_files_ok": False,
        "ui_styles_source_files_ok": False,
        "todos_source_files_ok": False,

        "feature_counts_ok": False,
        "code_style_counts_ok": False,
        "security_counts_ok": False,
        "ui_styles_counts_ok": False,
        "todos_counts_ok": False,

        "feature_entries_ok": False,
        "code_style_entries_ok": False,
        "security_entries_ok": False,
        "ui_styles_entries_ok": False,
        "todos_entries_ok": False,

        "project_only_required_files": False,
    }

    # Compute expected from inputs
    expected = {}
    try:
        expected["features"] = compute_expected_features(feature_in)
    except Exception:
        expected["features"] = None
    try:
        expected["code_style"] = compute_expected_code_style(code_style_in)
    except Exception:
        expected["code_style"] = None
    try:
        expected["security"] = compute_expected_security(security_in)
    except Exception:
        expected["security"] = None
    try:
        expected["ui_styles"] = compute_expected_ui_styles(ui_styles_in)
    except Exception:
        expected["ui_styles"] = None
    try:
        expected["todos"] = compute_expected_todos(todos_in)
    except Exception:
        expected["todos"] = None

    # Check file existence
    if os.path.isfile(feature_out):
        checks["feature_file_exists"] = True
    if os.path.isfile(code_style_out):
        checks["code_style_file_exists"] = True
    if os.path.isfile(security_out):
        checks["security_file_exists"] = True
    if os.path.isfile(ui_styles_out):
        checks["ui_styles_file_exists"] = True
    if os.path.isfile(todos_out):
        checks["todos_file_exists"] = True

    # Validate JSON and schema/content per file
    # Feature tracker
    if checks["feature_file_exists"]:
        try:
            feat_obj = load_output_json(feature_out)
            checks["feature_json_valid"] = True
            keys_ok, cat_ok, sf_ok = validate_top_level(feat_obj, "features", ["input/features.jsonl"])
            checks["feature_schema_ok"] = keys_ok
            checks["feature_category_ok"] = cat_ok
            checks["feature_source_files_ok"] = sf_ok
            if isinstance(feat_obj, dict) and "entries" in feat_obj and "counts" in feat_obj:
                if isinstance(feat_obj["counts"], dict) and set(feat_obj["counts"].keys()) == {"total"} and isinstance(feat_obj["entries"], list):
                    checks["feature_counts_ok"] = (feat_obj["counts"].get("total") == len(feat_obj["entries"]))
            # Entries strict compare
            if expected.get("features") is not None and "entries" in feat_obj:
                req_keys = ["id", "title", "status", "description", "component"]
                checks["feature_entries_ok"] = compare_entries_strict(expected["features"]["entries"], feat_obj.get("entries"), req_keys)
        except Exception:
            pass

    # Code style tracker
    if checks["code_style_file_exists"]:
        try:
            cs_obj = load_output_json(code_style_out)
            checks["code_style_json_valid"] = True
            keys_ok, cat_ok, sf_ok = validate_top_level(cs_obj, "code_style", ["input/code_style.yaml"])
            checks["code_style_schema_ok"] = keys_ok
            checks["code_style_category_ok"] = cat_ok
            checks["code_style_source_files_ok"] = sf_ok
            if isinstance(cs_obj, dict) and "entries" in cs_obj and "counts" in cs_obj:
                if isinstance(cs_obj["counts"], dict) and set(cs_obj["counts"].keys()) == {"total"} and isinstance(cs_obj["entries"], list):
                    checks["code_style_counts_ok"] = (cs_obj["counts"].get("total") == len(cs_obj["entries"]))
            if expected.get("code_style") is not None and "entries" in cs_obj:
                req_keys = ["id", "rule", "rationale", "severity"]
                checks["code_style_entries_ok"] = compare_entries_strict(expected["code_style"]["entries"], cs_obj.get("entries"), req_keys)
        except Exception:
            pass

    # Security issues tracker
    if checks["security_file_exists"]:
        try:
            sec_obj = load_output_json(security_out)
            checks["security_json_valid"] = True
            keys_ok, cat_ok, sf_ok = validate_top_level(sec_obj, "security", ["input/security_issues.csv"])
            checks["security_schema_ok"] = keys_ok
            checks["security_category_ok"] = cat_ok
            checks["security_source_files_ok"] = sf_ok
            if isinstance(sec_obj, dict) and "entries" in sec_obj and "counts" in sec_obj:
                if isinstance(sec_obj["counts"], dict) and set(sec_obj["counts"].keys()) == {"total"} and isinstance(sec_obj["entries"], list):
                    checks["security_counts_ok"] = (sec_obj["counts"].get("total") == len(sec_obj["entries"]))
            if expected.get("security") is not None and "entries" in sec_obj:
                req_keys = ["id", "title", "severity", "status", "risk"]
                checks["security_entries_ok"] = compare_entries_strict(expected["security"]["entries"], sec_obj.get("entries"), req_keys)
        except Exception:
            pass

    # UI styles tracker
    if checks["ui_styles_file_exists"]:
        try:
            ui_obj = load_output_json(ui_styles_out)
            checks["ui_styles_json_valid"] = True
            keys_ok, cat_ok, sf_ok = validate_top_level(ui_obj, "ui_styles", ["input/ui_styles.json"])
            checks["ui_styles_schema_ok"] = keys_ok
            checks["ui_styles_category_ok"] = cat_ok
            checks["ui_styles_source_files_ok"] = sf_ok
            if isinstance(ui_obj, dict) and "entries" in ui_obj and "counts" in ui_obj:
                if isinstance(ui_obj["counts"], dict) and set(ui_obj["counts"].keys()) == {"total"} and isinstance(ui_obj["entries"], list):
                    checks["ui_styles_counts_ok"] = (ui_obj["counts"].get("total") == len(ui_obj["entries"]))
            if expected.get("ui_styles") is not None and "entries" in ui_obj:
                req_keys = ["type", "name", "value"]
                checks["ui_styles_entries_ok"] = compare_entries_strict(expected["ui_styles"]["entries"], ui_obj.get("entries"), req_keys)
        except Exception:
            pass

    # Todos tracker
    if checks["todos_file_exists"]:
        try:
            todo_obj = load_output_json(todos_out)
            checks["todos_json_valid"] = True
            keys_ok, cat_ok, sf_ok = validate_top_level(todo_obj, "todos", ["input/todos.tsv"])
            checks["todos_schema_ok"] = keys_ok
            checks["todos_category_ok"] = cat_ok
            checks["todos_source_files_ok"] = sf_ok
            if isinstance(todo_obj, dict) and "entries" in todo_obj and "counts" in todo_obj:
                if isinstance(todo_obj["counts"], dict) and set(todo_obj["counts"].keys()) == {"total"} and isinstance(todo_obj["entries"], list):
                    checks["todos_counts_ok"] = (todo_obj["counts"].get("total") == len(todo_obj["entries"]))
            if expected.get("todos") is not None and "entries" in todo_obj:
                req_keys = ["id", "task", "assignee", "due_date", "priority", "status"]
                checks["todos_entries_ok"] = compare_entries_strict(expected["todos"]["entries"], todo_obj.get("entries"), req_keys)
        except Exception:
            pass

    # Check only required files under output/project
    try:
        required_files = {
            "feature-tracker.json",
            "code-style-tracker.json",
            "security-issues.json",
            "ui-styles.json",
            "todolist.json",
        }
        if os.path.isdir(out_project_dir):
            present = set(os.listdir(out_project_dir))
            # Ignore non-files? Requirement is only write the five files; ensure present equals required
            # If there are directories or non-json files, fail
            # Compare only files
            present_files = set([name for name in present if os.path.isfile(os.path.join(out_project_dir, name))])
            if present_files == required_files:
                checks["project_only_required_files"] = True
    except Exception:
        pass

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure 0.0 if no outputs at all or missing required artifacts
    required_exist = (
        checks["feature_file_exists"] and
        checks["code_style_file_exists"] and
        checks["security_file_exists"] and
        checks["ui_styles_file_exists"] and
        checks["todos_file_exists"]
    )
    if not required_exist:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()