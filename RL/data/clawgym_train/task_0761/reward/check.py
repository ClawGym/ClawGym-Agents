import json
import os
import re
import sys
from typing import Any, Dict, List

def load_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_table(schema: Dict[str, Any], table_name: str) -> Dict[str, Any]:
    tables = schema.get("tables")
    if isinstance(tables, dict):
        return tables.get(table_name, {})
    # if tables presented as list
    if isinstance(tables, list):
        for t in tables:
            if isinstance(t, dict) and t.get("name") == table_name:
                return t
    return {}

def columns_list(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    cols = table.get("columns")
    if isinstance(cols, list):
        return [c for c in cols if isinstance(c, dict)]
    return []

def has_required_columns(table: Dict[str, Any], required: List[str]) -> bool:
    cols = columns_list(table)
    names = {c.get("name") for c in cols if isinstance(c.get("name"), str)}
    return all(r in names for r in required)

def check_columns_have_fields(table: Dict[str, Any]) -> bool:
    cols = columns_list(table)
    required_keys = {"name", "type", "required", "description"}
    for c in cols:
        if not required_keys.issubset(set(c.keys())):
            return False
        # required must be boolean
        if not isinstance(c.get("required"), bool):
            return False
    return True

def check_angles_items(items: List[Dict[str, Any]]) -> bool:
    for it in items:
        # mandatory fields presence
        keys = {"angle","relevance","outcome_clarity","proof_support","differentiation","execution_simplicity","risk","total","rank","rationale"}
        if not keys.issubset(set(it.keys())):
            return False
        # types and ranges
        for k in ["relevance","outcome_clarity","proof_support","differentiation","execution_simplicity","risk"]:
            v = it.get(k)
            if not isinstance(v, int) or not (1 <= v <= 10):
                return False
        total = it.get("total")
        if not isinstance(total, int) or not (0 <= total <= 50):
            return False
        rank = it.get("rank")
        if not isinstance(rank, int) or rank <= 0:
            return False
        if not isinstance(it.get("angle"), str):
            return False
        if not isinstance(it.get("rationale"), str):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # 1) scan_nas.py checks
    scan_path = os.path.join(output_dir, "scan_nas.py")
    scan_text = load_text(scan_path)
    checks["scan_exists"] = os.path.isfile(scan_path) and scan_path.endswith(".py")
    checks["scan_has_imports"] = False
    checks["scan_has_traversal"] = False
    checks["scan_has_flags"] = False
    checks["scan_docstring_mentions"] = False
    checks["scan_no_dangerous_ops"] = False

    if checks["scan_exists"]:
        # imports argparse and json
        has_argparse = ("import argparse" in scan_text) or ("from argparse import" in scan_text)
        has_json = ("import json" in scan_text) or ("from json import" in scan_text)
        checks["scan_has_imports"] = has_argparse and has_json

        # traversal: os.walk or rglob
        checks["scan_has_traversal"] = ("os.walk" in scan_text) or (".rglob(" in scan_text)

        # flags
        checks["scan_has_flags"] = ("--root" in scan_text) and ("--follow-symlinks" in scan_text)

        # top-level docstring mentions read-only/offline: attempt to parse module docstring via ast
        docstring_ok = False
        try:
            import ast
            tree = ast.parse(scan_text)
            ds = ast.get_docstring(tree)
            if isinstance(ds, str):
                ds_lower = ds.lower()
                if ("read-only" in ds_lower or "readonly" in ds_lower or "read only" in ds_lower) and ("offline" in ds_lower):
                    docstring_ok = True
        except Exception:
            docstring_ok = False
        checks["scan_docstring_mentions"] = docstring_ok

        # dangerous operations not present
        dangerous_patterns = [
            r"os\.remove\s*\(",
            r"shutil\.rmtree\s*\(",
            r"os\.rename\s*\(",
            r"os\.chmod\s*\(",
        ]
        # open(..., 'w' / "w")
        open_w = re.search(r"\bopen\s*\([^)]*(['\"])w\1", scan_text) is not None
        others = any(re.search(p, scan_text) for p in dangerous_patterns)
        checks["scan_no_dangerous_ops"] = (not open_w) and (not others)

    # 2) schema.json checks
    schema_path = os.path.join(output_dir, "schema.json")
    schema = load_json(schema_path)
    checks["schema_valid_json"] = isinstance(schema, dict)
    checks["schema_has_tables"] = False
    checks["schema_files_required_columns"] = False
    checks["schema_directories_required_columns"] = False
    checks["schema_columns_fields_present"] = False
    if checks["schema_valid_json"]:
        has_tables_key = "tables" in schema
        checks["schema_has_tables"] = has_tables_key
        if has_tables_key:
            files_table = find_table(schema, "files")
            dirs_table = find_table(schema, "directories")
            files_required = ["path","name","size","mtime","ctime","atime","is_symlink","extension","directory_path"]
            dirs_required = ["path","name","parent_path"]
            checks["schema_files_required_columns"] = bool(files_table) and has_required_columns(files_table, files_required)
            checks["schema_directories_required_columns"] = bool(dirs_table) and has_required_columns(dirs_table, dirs_required)
            # columns have required fields
            all_cols_ok = False
            if files_table and dirs_table:
                all_cols_ok = check_columns_have_fields(files_table) and check_columns_have_fields(dirs_table)
            checks["schema_columns_fields_present"] = all_cols_ok

    # 3) report_template.html checks
    report_path = os.path.join(output_dir, "report_template.html")
    report_text = load_text(report_path)
    checks["report_has_basic_tags"] = all(tag in report_text.lower() for tag in ["<html", "<head", "<body"])
    checks["report_has_file_input"] = 'type="file"' in report_text.lower()
    checks["report_uses_filereader"] = "filereader(" in report_text.lower()
    checks["report_has_summaries_text"] = ("Total files" in report_text) and ("extensions" in report_text.lower())
    # ensure no external script/link tags with http/https
    no_ext_links = True
    rt_lower = report_text.lower()
    # Check for script/link tags with http or https
    if re.search(r"<script[^>]+src=[\"']https?://", rt_lower):
        no_ext_links = False
    if re.search(r"<link[^>]+href=[\"']https?://", rt_lower):
        no_ext_links = False
    checks["report_no_external_links"] = no_ext_links

    # 4) resources.json checks
    resources_path = os.path.join(output_dir, "resources.json")
    resources = load_json(resources_path)
    checks["resources_valid_json"] = isinstance(resources, list)
    checks["resources_min_items"] = False
    checks["resources_items_have_fields"] = False
    checks["resources_urls_http"] = False
    checks["resources_licenses_open"] = False
    if checks["resources_valid_json"]:
        checks["resources_min_items"] = len(resources) >= 5
        fields_ok = True
        urls_ok = True
        licenses_ok = True
        license_indicators = ["mit", "apache", "gpl", "bsd", "mpl", "cc", "free", "osl", "epl"]
        for item in resources:
            if not isinstance(item, dict):
                fields_ok = False
                break
            for k in ["name","type","license","url","why_it_fits"]:
                if k not in item:
                    fields_ok = False
                    break
            if not isinstance(item.get("url",""), str) or not item.get("url","").startswith("http"):
                urls_ok = False
            lic = str(item.get("license","")).lower()
            if not any(ind in lic for ind in license_indicators):
                licenses_ok = False
        checks["resources_items_have_fields"] = fields_ok
        checks["resources_urls_http"] = urls_ok
        checks["resources_licenses_open"] = licenses_ok

    # 5) project_plan.md checks
    plan_path = os.path.join(output_dir, "project_plan.md")
    plan_text = load_text(plan_path)
    headings = ["## Objectives","## Tasks","## Timeline","## Risks","## Acceptance Criteria"]
    checks["plan_has_headings"] = all(h in plan_text for h in headings)
    # Ensure at least one bullet under each heading
    checks["plan_each_section_has_bullet"] = False
    if checks["plan_has_headings"]:
        lines = plan_text.splitlines()
        # map heading indices
        indices = []
        for i, line in enumerate(lines):
            if line.strip() in headings:
                indices.append((line.strip(), i))
        has_bullet_each = True
        for idx, (heading, start) in enumerate(indices):
            end = indices[idx+1][1] if idx+1 < len(indices) else len(lines)
            section_lines = lines[start+1:end]
            has_bullet = any(l.strip().startswith(("-", "*")) for l in section_lines if l.strip())
            if not has_bullet:
                has_bullet_each = False
                break
        checks["plan_each_section_has_bullet"] = has_bullet_each

    # 6) landing_angles.json checks
    angles_path = os.path.join(output_dir, "landing_angles.json")
    angles_json = load_json(angles_path)
    checks["angles_valid_json"] = isinstance(angles_json, dict)
    checks["angles_min_count"] = False
    checks["angles_items_fields_and_types"] = False
    checks["angles_total_in_range"] = False
    checks["angles_ranks_top3_present"] = False
    checks["angles_top3_array_valid"] = False
    if checks["angles_valid_json"]:
        angles_list = angles_json.get("angles")
        if isinstance(angles_list, list):
            checks["angles_min_count"] = len(angles_list) >= 5
            items_ok = check_angles_items(angles_list)
            checks["angles_items_fields_and_types"] = items_ok
            # total in range is already part of items check; but ensure separate bool if any item passes?
            # Here we require all items have total in range to be True.
            totals_ok = True
            ranks = set()
            for it in angles_list:
                t = it.get("total")
                if not (isinstance(t, int) and 0 <= t <= 50):
                    totals_ok = False
                r = it.get("rank")
                if isinstance(r, int):
                    ranks.add(r)
            checks["angles_total_in_range"] = totals_ok
            checks["angles_ranks_top3_present"] = {1,2,3}.issubset(ranks)
        # top3 array
        top3 = angles_json.get("top3")
        top3_ok = isinstance(top3, list) and len(top3) == 3
        if top3_ok:
            for t in top3:
                if not isinstance(t, dict):
                    top3_ok = False
                    break
                if not all(isinstance(t.get(k), str) for k in ["angle","why_it_wins","best_use_context"]):
                    top3_ok = False
                    break
        checks["angles_top3_array_valid"] = bool(top3_ok)

    # 7) README.md checks
    readme_path = os.path.join(output_dir, "README.md")
    readme_text = load_text(readme_path)
    readme_lower = readme_text.lower()
    checks["readme_has_phrases"] = ("read-only" in readme_lower or "read only" in readme_lower) and ("offline" in readme_lower)
    checks["readme_mentions_root_flag"] = "--root" in readme_text

    # Compute reward
    # Only positive contributions from output-dependent checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    # No-op baseline: if no outputs exist (output dir missing or empty), reward must be 0.0
    output_exists = os.path.isdir(output_dir)
    any_output_file = False
    if output_exists:
        for _root, _dirs, files in os.walk(output_dir):
            if files:
                any_output_file = True
                break
    if not any_output_file:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()