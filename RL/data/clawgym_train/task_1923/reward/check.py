import json
import os
import sys
from collections import OrderedDict

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except:
        return None

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None

def check_no_absolute_paths(path):
    data = read_text(path)
    if data is None:
        return False
    for line in data.splitlines():
        if line.startswith("/") or line.startswith("~/"):
            return False
    return True

def is_valid_json_export(obj):
    if not isinstance(obj, list):
        return False
    for item in obj:
        if not isinstance(item, dict):
            return False
        for key in ("type", "time", "value"):
            if key not in item or not isinstance(item[key], str):
                return False
    return True

def parse_jsonl_lines(path):
    content = read_text(path)
    if content is None:
        return None
    lines = [ln for ln in content.splitlines() if ln.strip() != ""]
    objs = []
    for ln in lines:
        try:
            o = json.loads(ln)
            objs.append(o)
        except:
            return None
    return objs

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = OrderedDict()

    # Required files
    json_path = os.path.join(output_dir, "etl_export.json")
    csv_path = os.path.join(output_dir, "etl_export.csv")
    commands_path = os.path.join(output_dir, "commands_run.jsonl")
    audit_path = os.path.join(output_dir, "audit.md")

    # Categories expected
    required_categories = [
        "ingest", "transform", "validate", "schema", "aggregate", "query",
        "filter", "export", "sample", "profile", "pipeline", "visualize"
    ]

    # 1) JSON export checks
    checks["json_exists"] = os.path.isfile(json_path)
    json_obj = load_json(json_path) if checks["json_exists"] else None
    checks["json_valid_array_objects"] = is_valid_json_export(json_obj) if json_obj is not None else False

    # Has all required categories in JSON types
    json_types = set()
    if checks["json_valid_array_objects"]:
        for item in json_obj:
            t = item.get("type")
            if isinstance(t, str):
                json_types.add(t)
    checks["json_all_types_present"] = checks["json_valid_array_objects"] and all(cat in json_types for cat in required_categories)

    # 2) CSV export checks
    checks["csv_exists"] = os.path.isfile(csv_path)
    csv_text = read_text(csv_path) if checks["csv_exists"] else None
    lines = csv_text.splitlines() if csv_text is not None else []
    header = lines[0].strip() if len(lines) >= 1 else ""
    checks["csv_header_ok"] = header == "type,time,value"
    # Non-empty means at least one data row beyond header
    data_rows = len(lines) - 1 if len(lines) >= 1 else 0
    checks["csv_nonempty_with_data"] = data_rows >= 1
    json_len = len(json_obj) if checks["json_valid_array_objects"] else 0
    # Only validate rows >= json length when both files exist and JSON valid
    checks["csv_rows_ge_json"] = checks["csv_exists"] and checks["json_valid_array_objects"] and (data_rows >= json_len)

    # 3) Substring checks on JSON value fields
    substrings = {
        "json_contains_input_users_2026_04_csv": "input/users_2026-04.csv",
        "json_contains_normalize_email": "Normalize email to lowercase",
        "json_contains_not_null_user_id": "NOT NULL check on user_id",
        "json_contains_email_matches_regex": "email matches regex",
        "json_contains_signup_date_parseable": "signup_date parseable",
        "json_contains_users_dim_v2": "users_dim v2",
        "json_contains_daily_signups_by_country": "Daily signups by country",
        "json_contains_exclude_email_domains_test_com": "Exclude email domains: test.com",
        "json_contains_sample_10000_seed_42": "Sample 10000 rows stratified by country (seed=42)",
        "json_contains_top_10_email_domains": "Top 10 email domains",
        "json_contains_postgresql_uri": "postgresql://warehouse/public.users_dim",
        "json_contains_daily_user_etl": "daily_user_etl",
    }
    values_joined = ""
    if checks["json_valid_array_objects"]:
        try:
            values_joined = "\n".join(item.get("value", "") for item in json_obj if isinstance(item, dict))
        except:
            values_joined = ""
    for key, needle in substrings.items():
        checks[key] = checks["json_valid_array_objects"] and (needle in values_joined)

    # 4) commands_run.jsonl checks
    checks["commands_jsonl_exists"] = os.path.isfile(commands_path)
    commands_objs = parse_jsonl_lines(commands_path) if checks["commands_jsonl_exists"] else None
    checks["commands_jsonl_valid"] = (commands_objs is not None) and all(
        isinstance(o, dict) and isinstance(o.get("type"), str) and isinstance(o.get("value"), str)
        for o in (commands_objs or [])
    )
    # At least 12 lines
    checks["commands_at_least_12_lines"] = checks["commands_jsonl_valid"] and (len(commands_objs) >= 12 if commands_objs is not None else False)
    # Cover all categories
    cmd_types = set(o.get("type") for o in commands_objs) if checks["commands_jsonl_valid"] else set()
    checks["commands_cover_all_categories"] = checks["commands_jsonl_valid"] and all(cat in cmd_types for cat in required_categories)

    # 5) audit.md checks
    checks["audit_md_exists"] = os.path.isfile(audit_path)
    audit_text = read_text(audit_path) if checks["audit_md_exists"] else ""
    checks["audit_has_title"] = checks["audit_md_exists"] and any(line.startswith("# ETL Audit") for line in audit_text.splitlines())
    checks["audit_has_counts_section"] = checks["audit_md_exists"] and ("Counts by Command" in audit_text)
    checks["audit_has_logged_entries_section"] = checks["audit_md_exists"] and ("Logged Entries" in audit_text)
    checks["audit_has_notes_assumptions"] = checks["audit_md_exists"] and ("Notes & Assumptions" in audit_text)
    checks["audit_has_next_steps"] = checks["audit_md_exists"] and ("Next Steps" in audit_text)
    checks["audit_contains_users_dim_v2"] = checks["audit_md_exists"] and ("users_dim v2" in audit_text)
    checks["audit_contains_daily_user_etl"] = checks["audit_md_exists"] and ("daily_user_etl" in audit_text)

    # 6) Absolute path leakage checks
    checks["no_abs_paths_in_json"] = check_no_absolute_paths(json_path) if checks["json_exists"] else False
    checks["no_abs_paths_in_csv"] = check_no_absolute_paths(csv_path) if checks["csv_exists"] else False
    checks["no_abs_paths_in_commands"] = check_no_absolute_paths(commands_path) if checks["commands_jsonl_exists"] else False
    checks["no_abs_paths_in_audit"] = check_no_absolute_paths(audit_path) if checks["audit_md_exists"] else False

    # Compute reward: fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure no-op baseline yields 0.0
    # If output dir missing or empty and no files exist, passed will be 0, reward 0.0 naturally.

    result = OrderedDict()
    result["reward"] = round(reward, 6)
    for k, v in checks.items():
        result[k] = bool(v)

    print(json.dumps(result))

if __name__ == "__main__":
    main()