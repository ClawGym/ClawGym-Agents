import json
import os
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def first_nonempty_line(text):
    if text is None:
        return None
    for line in text.splitlines():
        if line.strip():
            return line.rstrip("\n")
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "status_has_version": False,
        "status_has_ok": False,
        "stats_has_total": False,
        "export_json_exists_and_array": False,
        "export_csv_header_ok": False,
        "search_hvac_contains": False,
        "search_water_contains": False,
        "plan_summary_has_required_substrings": False,
        "notifications_yaml_has_top_level_reminders_key": False,
    }

    # 1) output/status.txt — contains both "Version: v2.0.0" and "Status: OK".
    status_path = os.path.join(output_dir, "status.txt")
    status_text = read_text_file(status_path)
    if status_text is not None:
        if "Version: v2.0.0" in status_text:
            checks["status_has_version"] = True
        if "Status: OK" in status_text:
            checks["status_has_ok"] = True

    # 2) output/stats.txt — contains substring "Total:".
    stats_path = os.path.join(output_dir, "stats.txt")
    stats_text = read_text_file(stats_path)
    if stats_text is not None and "Total:" in stats_text:
        checks["stats_has_total"] = True

    # 3) output/export.json — exists, valid JSON, top-level array, starts with '[' and ends with ']'
    export_json_path = os.path.join(output_dir, "export.json")
    export_json_text = read_text_file(export_json_path)
    if export_json_text is not None:
        raw = export_json_text.strip()
        try:
            data = json.loads(export_json_text)
            if isinstance(data, list) and raw.startswith("[") and raw.endswith("]"):
                checks["export_json_exists_and_array"] = True
        except Exception:
            pass

    # 4) output/export.csv — first non-empty line exactly "type,time,value"
    export_csv_path = os.path.join(output_dir, "export.csv")
    export_csv_text = read_text_file(export_csv_path)
    if export_csv_text is not None:
        header = first_nonempty_line(export_csv_text)
        if header == "type,time,value":
            checks["export_csv_header_ok"] = True

    # 5) output/search_hvac.txt — contains "HVAC" (case-insensitive)
    search_hvac_path = os.path.join(output_dir, "search_hvac.txt")
    search_hvac_text = read_text_file(search_hvac_path)
    if search_hvac_text is not None and "hvac" in search_hvac_text.lower():
        checks["search_hvac_contains"] = True

    # 6) output/search_water.txt — contains "water" (case-insensitive)
    search_water_path = os.path.join(output_dir, "search_water.txt")
    search_water_text = read_text_file(search_water_path)
    if search_water_text is not None and "water" in search_water_text.lower():
        checks["search_water_contains"] = True

    # 7) output/plan_summary.md — includes required substrings and exact total cost line
    plan_summary_path = os.path.join(output_dir, "plan_summary.md")
    plan_summary_text = read_text_file(plan_summary_path)
    if plan_summary_text is not None:
        required_substrings = ["Inventory", "Schedule", "Reminders", "Checklist", "Costs", "2026-Q2"]
        has_all_required = all(s in plan_summary_text for s in required_substrings)
        # Exact total line
        total_line_needed = "Total Quarterly Cost: $391.50"
        has_total_line = any((line.strip() == total_line_needed) for line in plan_summary_text.splitlines())
        if has_all_required and has_total_line:
            checks["plan_summary_has_required_substrings"] = True

    # 8) output/notifications.yaml — contains top-level key name "reminders:"
    notifications_path = os.path.join(output_dir, "notifications.yaml")
    notifications_text = read_text_file(notifications_path)
    if notifications_text is not None:
        found_top_level = False
        for line in notifications_text.splitlines():
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("reminders:"):
                found_top_level = True
                break
        if found_top_level:
            checks["notifications_yaml_has_top_level_reminders_key"] = True

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()