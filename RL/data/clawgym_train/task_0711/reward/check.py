import json
import os
import sys
import csv
import re
from collections import OrderedDict

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def detect_project_code_column(fieldnames):
    if not fieldnames:
        return None
    lower = [fn.strip().lower() for fn in fieldnames]
    candidates = ["project_code", "codename", "project", "code", "projectname", "name"]
    for c in candidates:
        for i, fn in enumerate(lower):
            if fn == c:
                return fieldnames[i]
    # Fallback to first column
    return fieldnames[0]

def read_projects_from_csv(csv_path):
    projects = []
    if not os.path.isfile(csv_path):
        return projects
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            # Try DictReader first
            sniffer = csv.Sniffer()
            sample = f.read(1024)
            f.seek(0)
            has_header = False
            try:
                has_header = sniffer.has_header(sample)
            except Exception:
                has_header = True
            if has_header:
                reader = csv.DictReader(f)
                code_col = detect_project_code_column(reader.fieldnames or [])
                for row in reader:
                    if not isinstance(row, dict):
                        continue
                    val = (row.get(code_col) or "").strip()
                    if val:
                        projects.append(val)
            else:
                f.seek(0)
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    val = (row[0] or "").strip()
                    if val:
                        projects.append(val)
    except Exception:
        return []
    return projects

def is_short_query(s):
    if not isinstance(s, str):
        return False
    words = re.split(r"\s+", s.strip())
    # Treat empty string as 0 words (invalid)
    count = len([w for w in words if w])
    return count > 0 and count <= 8

def validate_project_entry(project_obj):
    # Check required keys and types
    if not isinstance(project_obj, dict):
        return False, False, False, False
    required_keys = [
        "project_code", "queries", "memory_found", "task_summaries",
        "timeline_notes", "preferences", "what_worked", "what_failed",
        "open_issues", "next_steps"
    ]
    for k in required_keys:
        if k not in project_obj:
            return False, False, False, False

    # Field type checks
    fields_ok = True
    if not isinstance(project_obj.get("project_code"), str) or not project_obj.get("project_code").strip():
        fields_ok = False
    if not isinstance(project_obj.get("queries"), list):
        fields_ok = False
    if not isinstance(project_obj.get("memory_found"), bool):
        fields_ok = False
    if not isinstance(project_obj.get("task_summaries"), list):
        fields_ok = False
    if not isinstance(project_obj.get("timeline_notes"), list):
        fields_ok = False
    prefs = project_obj.get("preferences")
    if not (isinstance(prefs, list) or isinstance(prefs, dict)):
        fields_ok = False
    if not isinstance(project_obj.get("what_worked"), str):
        fields_ok = False
    if not isinstance(project_obj.get("what_failed"), str):
        fields_ok = False
    if not (isinstance(project_obj.get("open_issues"), list) and len(project_obj.get("open_issues")) >= 1):
        fields_ok = False
    if not (isinstance(project_obj.get("next_steps"), list) and len(project_obj.get("next_steps")) >= 1):
        fields_ok = False

    # Queries check: at least 2, each <= 8 words, and at least one contains "role='user'"
    queries_ok = False
    queries = project_obj.get("queries", [])
    if isinstance(queries, list) and len(queries) >= 2 and all(isinstance(q, str) for q in queries):
        if all(is_short_query(q) for q in queries):
            if any("role='user'" in q for q in queries):
                queries_ok = True

    return True, fields_ok, queries_ok, True  # last True is a placeholder for extensibility

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "brief_exists": False,
        "brief_valid_json": False,
        "brief_has_generated_at": False,
        "brief_has_three_projects": False,
        "brief_project_codes_match_csv": False,
        "brief_queries_valid_all_projects": False,
        "brief_fields_present_all_projects": False,
        "brief_unknown_present": False,
        "search_log_exists_nonempty": False,
        "search_log_contains_all_project_names": False,
        "search_log_search_tags_ge6": False,
        "search_log_has_summary_tag": False,
        "search_log_has_timeline_tag": False,
        "assumptions_exists_nonempty": False,
        "assumptions_has_dash_line": False,
    }

    # Paths
    brief_path = os.path.join(output_dir, "brief.json")
    search_log_path = os.path.join(output_dir, "search_log.md")
    assumptions_path = os.path.join(output_dir, "assumptions.txt")
    projects_csv_path = os.path.join(input_dir, "projects.csv")

    # Load expected project names from CSV (reference)
    expected_projects = read_projects_from_csv(projects_csv_path)
    # Use only the first three non-empty codes for validation
    expected_projects = [p for p in expected_projects if p.strip()][:3]

    # Check brief.json
    if os.path.isfile(brief_path):
        checks["brief_exists"] = True
        brief = parse_json_file(brief_path)
        if isinstance(brief, dict):
            checks["brief_valid_json"] = True

            # generated_at
            if isinstance(brief.get("generated_at"), str) and brief.get("generated_at").strip():
                checks["brief_has_generated_at"] = True

            # projects
            projects = brief.get("projects")
            if isinstance(projects, list) and len(projects) == 3:
                checks["brief_has_three_projects"] = True

                # Validate fields and queries for all projects
                all_fields_ok = True
                all_queries_ok = True
                project_codes = []
                for proj in projects:
                    has_required, fields_ok, queries_ok, _ = validate_project_entry(proj)
                    if not has_required or not fields_ok:
                        all_fields_ok = False
                    if not queries_ok:
                        all_queries_ok = False
                    if isinstance(proj, dict) and isinstance(proj.get("project_code"), str):
                        project_codes.append(proj.get("project_code"))

                if all_fields_ok:
                    checks["brief_fields_present_all_projects"] = True
                if all_queries_ok:
                    checks["brief_queries_valid_all_projects"] = True

                # Match project codes with CSV (if we have three expected)
                if len(expected_projects) == 3:
                    # Compare case-insensitive sets
                    set_expected = set([p.strip().lower() for p in expected_projects])
                    set_actual = set([c.strip().lower() for c in project_codes if isinstance(c, str)])
                    if set_actual == set_expected:
                        checks["brief_project_codes_match_csv"] = True

            # unknown presence in JSON content
            try:
                brief_str = json.dumps(brief).lower()
                if "unknown" in brief_str:
                    checks["brief_unknown_present"] = True
            except Exception:
                pass

    # search_log.md checks
    text = read_file_text(search_log_path)
    if isinstance(text, str):
        if text.strip():
            checks["search_log_exists_nonempty"] = True
            # Must contain all three project names (case-insensitive)
            if len(expected_projects) == 3:
                if all((p.lower() in text.lower()) for p in expected_projects):
                    checks["search_log_contains_all_project_names"] = True

            # Count tags
            if text.count("[SEARCH]") >= 6:
                checks["search_log_search_tags_ge6"] = True
            if "[SUMMARY]" in text:
                checks["search_log_has_summary_tag"] = True
            if "[TIMELINE]" in text:
                checks["search_log_has_timeline_tag"] = True

    # assumptions.txt checks
    assumptions = read_file_text(assumptions_path)
    if isinstance(assumptions, str) and assumptions.strip():
        checks["assumptions_exists_nonempty"] = True
        # At least one line starting with "- "
        lines = assumptions.splitlines()
        if any(line.startswith("- ") for line in lines):
            checks["assumptions_has_dash_line"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if no outputs, ensure 0.0
    outputs_present = any(os.path.isfile(p) for p in [brief_path, search_log_path, assumptions_path])
    if not outputs_present:
        reward = 0.0

    result = OrderedDict()
    result["reward"] = round(reward, 6)
    for k, v in checks.items():
        result[k] = v
    print(json.dumps(result))

if __name__ == "__main__":
    main()