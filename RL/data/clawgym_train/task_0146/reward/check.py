import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def detect_path_leak(text):
    # Detect obvious absolute/home path leaks
    # We intentionally check common patterns only to avoid false positives
    patterns = [
        "~/.openclaw",
        "/root/",
        "/home/",
        "/Users/",
        "C:\\\\Users\\\\",
        "C:/Users/",
    ]
    for p in patterns:
        if p in text:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # Path leak check
        "no_path_leak": False,

        # memory_export.json checks
        "export_exists": False,
        "export_valid_json": False,
        "export_has_memories_array": False,
        "export_required_keys": False,
        "export_categories_ok": False,
        "export_updated_value": False,
        "export_excludes_forgotten": False,

        # search_results.json checks
        "search_exists": False,
        "search_valid_json": False,
        "search_has_queries": False,
        "search_inclusions": False,
        "search_jwt_empty": False,

        # stats_snapshot.json checks
        "stats_exists": False,
        "stats_valid_json": False,
        "stats_numeric_fields": False,
        "stats_thresholds": False,

        # maintenance_report.json checks
        "maint_exists": False,
        "maint_valid_json": False,
        "maint_numeric_fields": False,
        "maint_thresholds": False,
    }

    # Output file paths
    export_path = os.path.join(output_dir, "memory_export.json")
    search_path = os.path.join(output_dir, "search_results.json")
    stats_path = os.path.join(output_dir, "stats_snapshot.json")
    maint_path = os.path.join(output_dir, "maintenance_report.json")

    # Path leak check: only runs if files exist, and all must be clean
    leak_free = True
    any_output_file = False
    for p in [export_path, search_path, stats_path, maint_path]:
        if os.path.isfile(p):
            any_output_file = True
            t = file_text(p)
            if detect_path_leak(t):
                leak_free = False
    if any_output_file and leak_free:
        checks["no_path_leak"] = True

    # 1) Validate memory_export.json
    mem_obj = None
    mem_list = None
    if os.path.isfile(export_path):
        checks["export_exists"] = True
        mem_obj = load_json(export_path)
        if isinstance(mem_obj, dict):
            checks["export_valid_json"] = True
            memories = mem_obj.get("memories")
            if isinstance(memories, list):
                checks["export_has_memories_array"] = True
                mem_list = memories

                # Build dict by key for fast lookup
                mem_by_key = {}
                for m in mem_list:
                    if isinstance(m, dict) and "key" in m:
                        mem_by_key[str(m.get("key"))] = m

                # Required keys presence
                required_keys = ["user_name", "editor_pref", "stack", "deployment_rule"]
                has_all = all(k in mem_by_key for k in required_keys)
                checks["export_required_keys"] = has_all

                # Categories must match expected
                categories_ok = False
                if has_all:
                    expected_categories = {
                        "user_name": "facts",
                        "editor_pref": "preferences",
                        "stack": "technical",
                        "deployment_rule": "instructions",
                    }
                    categories_ok = True
                    for k, expected_cat in expected_categories.items():
                        cat = mem_by_key[k].get("category")
                        if cat != expected_cat:
                            categories_ok = False
                            break
                checks["export_categories_ok"] = categories_ok

                # Updated value for editor_pref
                updated_ok = False
                if "editor_pref" in mem_by_key:
                    val = mem_by_key["editor_pref"].get("value")
                    if val == "User prefers Neovim":
                        updated_ok = True
                checks["export_updated_value"] = updated_ok

                # Forgotten key must not be present
                checks["export_excludes_forgotten"] = ("auth_method" not in mem_by_key)

    # 2) Validate search_results.json
    search_obj = None
    if os.path.isfile(search_path):
        checks["search_exists"] = True
        search_obj = load_json(search_path)
        if isinstance(search_obj, dict):
            checks["search_valid_json"] = True
            # Presence of required queries and array types
            required_queries = ["vim", "deploy", "PostgreSQL", "JWT"]
            has_queries = True
            for q in required_queries:
                if q not in search_obj or not isinstance(search_obj[q], list):
                    has_queries = False
                    break
            checks["search_has_queries"] = has_queries

            # Inclusion checks
            inclusions_ok = False
            jwt_empty_ok = False
            if has_queries:
                inclusions_ok = (
                    "editor_pref" in search_obj.get("vim", []) and
                    "deployment_rule" in search_obj.get("deploy", []) and
                    "stack" in search_obj.get("PostgreSQL", [])
                )
                jwt_empty_ok = (len(search_obj.get("JWT", [])) == 0)
            checks["search_inclusions"] = inclusions_ok
            checks["search_jwt_empty"] = jwt_empty_ok

    # 3) Validate stats_snapshot.json
    stats_obj = None
    if os.path.isfile(stats_path):
        checks["stats_exists"] = True
        stats_obj = load_json(stats_path)
        if isinstance(stats_obj, dict):
            checks["stats_valid_json"] = True
            numeric_fields_ok = False
            thresholds_ok = False
            needed = ["total_stores", "total_updates", "total_deletes", "total_retrievals", "total_tokens_saved"]
            if all(k in stats_obj and is_number(stats_obj.get(k)) for k in needed):
                numeric_fields_ok = True
                ts = stats_obj.get("total_stores", 0)
                tu = stats_obj.get("total_updates", 0)
                td = stats_obj.get("total_deletes", 0)
                tts = stats_obj.get("total_tokens_saved", 0)
                if ts >= 5 and tu >= 1 and td >= 1 and tts >= 137:
                    thresholds_ok = True
            checks["stats_numeric_fields"] = numeric_fields_ok
            checks["stats_thresholds"] = thresholds_ok

    # 4) Validate maintenance_report.json
    maint_obj = None
    if os.path.isfile(maint_path):
        checks["maint_exists"] = True
        maint_obj = load_json(maint_path)
        if isinstance(maint_obj, dict):
            checks["maint_valid_json"] = True
            numeric_fields_ok = False
            thresholds_ok = False
            needed_m = ["active_count", "archive_count", "pruned_count", "deduped_count"]
            if all(k in maint_obj and is_number(maint_obj.get(k)) for k in needed_m):
                numeric_fields_ok = True
                ac = maint_obj.get("active_count", None)
                arc = maint_obj.get("archive_count", None)
                pr = maint_obj.get("pruned_count", None)
                dd = maint_obj.get("deduped_count", None)
                if ac == 4 and arc is not None and arc >= 1 and pr == 0 and dd == 0:
                    thresholds_ok = True
            checks["maint_numeric_fields"] = numeric_fields_ok
            checks["maint_thresholds"] = thresholds_ok

    # Compute reward as the fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # No-op baseline: if output dir missing or no expected files, keep reward 0.0
    # If none of the four primary files exist, force reward to 0.0
    primary_exist = any(os.path.isfile(p) for p in [export_path, search_path, stats_path, maint_path])
    if not primary_exist:
        reward = 0.0

    # Clamp reward between 0 and 1
    reward = max(0.0, min(1.0, float(reward)))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()