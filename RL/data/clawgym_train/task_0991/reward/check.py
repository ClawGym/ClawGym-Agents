import json
import os
import sys

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None

def read_first_line(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            line = f.readline()
            return line.rstrip("\r\n")
    except Exception:
        return None

def file_contains_line(path, substring):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if substring in line:
                    return True
        return False
    except Exception:
        return False

def count_dirs_files(base_dir):
    total_dirs = 0
    total_files = 0
    if not os.path.isdir(base_dir):
        return 0, 0
    for _, dirs, files in os.walk(base_dir):
        total_dirs += len(dirs)
        total_files += len(files)
    return total_dirs, total_files

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Directory structure
        "dir_knowledge": False,
        "dir_knowledge_projects": False,
        "dir_knowledge_areas": False,
        "dir_knowledge_resources": False,
        "dir_knowledge_archive": False,
        "dir_memory": False,
        "dir_memory_daily": False,
        "dir_scripts": False,
        # Files content checks
        "file_entities_heading": False,
        "file_tacit_heading": False,
        "file_memory_heading": False,
        "file_morning_script_copied": False,
        "file_nightly_script_copied": False,
        "file_agents_copied": False,
        "file_heartbeat_copied": False,
        "file_soul_heading": False,
        "file_user_heading_and_timezone": False,
        "file_tools_heading": False,
        # Daily note
        "daily_note_exists": False,
        "daily_note_first_line": False,
        "daily_note_setup_day": False,
        # Cron schedules
        "cron_schedules_valid_length": False,
        "cron_morning_valid": False,
        "cron_nightly_valid": False,
        # Report validation
        "report_json_valid": False,
        "report_counts_match": False,
        "report_daily_note_path_match": False,
        "report_timezone_match": False,
        "report_hours_match": False,
        "report_schedule_names": False,
    }

    # Load input config
    cfg_path = os.path.join(input_dir, "config.json")
    cfg = read_json(cfg_path)
    bot_name = user_name = timezone = None
    morning_hour = night_hour = None
    today = None

    if isinstance(cfg, dict):
        bot_name = cfg.get("bot_name")
        user_name = cfg.get("user_name")
        timezone = cfg.get("timezone")
        today = cfg.get("today")
        try:
            mh = cfg.get("morning_hour")
            morning_hour = int(mh) if mh is not None else None
        except Exception:
            morning_hour = None
        try:
            nh = cfg.get("night_hour")
            night_hour = int(nh) if nh is not None else None
        except Exception:
            night_hour = None

    # Define paths
    ws_out = os.path.join(output_dir, "workspace")
    knowledge_dir = os.path.join(ws_out, "knowledge")
    projects_dir = os.path.join(knowledge_dir, "projects")
    areas_dir = os.path.join(knowledge_dir, "areas")
    resources_dir = os.path.join(knowledge_dir, "resources")
    archive_dir = os.path.join(knowledge_dir, "archive")
    memory_dir = os.path.join(ws_out, "memory")
    daily_dir = os.path.join(memory_dir, "daily")
    scripts_dir = os.path.join(ws_out, "scripts")

    # Directory checks
    if os.path.isdir(knowledge_dir):
        checks["dir_knowledge"] = True
    if os.path.isdir(projects_dir):
        checks["dir_knowledge_projects"] = True
    if os.path.isdir(areas_dir):
        checks["dir_knowledge_areas"] = True
    if os.path.isdir(resources_dir):
        checks["dir_knowledge_resources"] = True
    if os.path.isdir(archive_dir):
        checks["dir_knowledge_archive"] = True
    if os.path.isdir(memory_dir):
        checks["dir_memory"] = True
    if os.path.isdir(daily_dir):
        checks["dir_memory_daily"] = True
    if os.path.isdir(scripts_dir):
        checks["dir_scripts"] = True

    # Files: headings
    entities_md = os.path.join(knowledge_dir, "entities.md")
    tacit_md = os.path.join(knowledge_dir, "tacit.md")
    memory_md = os.path.join(ws_out, "MEMORY.md")
    tools_md = os.path.join(ws_out, "TOOLS.md")
    soul_md = os.path.join(ws_out, "SOUL.md")
    user_md = os.path.join(ws_out, "USER.md")

    if os.path.isfile(entities_md):
        fl = read_first_line(entities_md)
        if fl == "# Known Entities":
            checks["file_entities_heading"] = True

    if os.path.isfile(tacit_md):
        fl = read_first_line(tacit_md)
        if fl == "# Tacit Knowledge — How Things Work":
            checks["file_tacit_heading"] = True

    if os.path.isfile(memory_md):
        fl = read_first_line(memory_md)
        if fl == "# Long-Term Memory":
            checks["file_memory_heading"] = True

    if os.path.isfile(tools_md):
        fl = read_first_line(tools_md)
        if fl == "# TOOLS.md - Local Notes":
            checks["file_tools_heading"] = True

    # SOUL.md heading with bot_name
    if os.path.isfile(soul_md) and isinstance(bot_name, str):
        fl = read_first_line(soul_md)
        expected = f"# {bot_name} — Soul"
        if fl == expected:
            checks["file_soul_heading"] = True

    # USER.md heading and timezone line
    if os.path.isfile(user_md) and isinstance(user_name, str) and isinstance(timezone, str):
        fl = read_first_line(user_md)
        expected = f"# About {user_name}"
        has_tz_line = file_contains_line(user_md, f"Timezone: {timezone}")
        if fl == expected and has_tz_line:
            checks["file_user_heading_and_timezone"] = True

    # Copy equality checks for templates and scripts
    # Inputs
    in_morning = os.path.join(input_dir, "scripts", "morning-daily-review.md")
    in_nightly = os.path.join(input_dir, "scripts", "nightly-memory-consolidation.md")
    in_agents = os.path.join(input_dir, "templates", "AGENTS.md")
    in_heartbeat = os.path.join(input_dir, "templates", "HEARTBEAT.md")
    # Outputs
    out_morning = os.path.join(scripts_dir, "morning-daily-review.md")
    out_nightly = os.path.join(scripts_dir, "nightly-memory-consolidation.md")
    out_agents = os.path.join(ws_out, "AGENTS.md")
    out_heartbeat = os.path.join(ws_out, "HEARTBEAT.md")

    # Morning script
    in_morning_b = read_bytes(in_morning)
    out_morning_b = read_bytes(out_morning)
    if in_morning_b is not None and out_morning_b is not None and in_morning_b == out_morning_b:
        checks["file_morning_script_copied"] = True

    # Nightly script
    in_nightly_b = read_bytes(in_nightly)
    out_nightly_b = read_bytes(out_nightly)
    if in_nightly_b is not None and out_nightly_b is not None and in_nightly_b == out_nightly_b:
        checks["file_nightly_script_copied"] = True

    # AGENTS.md
    in_agents_b = read_bytes(in_agents)
    out_agents_b = read_bytes(out_agents)
    if in_agents_b is not None and out_agents_b is not None and in_agents_b == out_agents_b:
        checks["file_agents_copied"] = True

    # HEARTBEAT.md
    in_heartbeat_b = read_bytes(in_heartbeat)
    out_heartbeat_b = read_bytes(out_heartbeat)
    if in_heartbeat_b is not None and out_heartbeat_b is not None and in_heartbeat_b == out_heartbeat_b:
        checks["file_heartbeat_copied"] = True

    # Daily note checks
    if isinstance(today, str):
        daily_note_path = os.path.join(daily_dir, f"{today}.md")
        if os.path.isfile(daily_note_path):
            checks["daily_note_exists"] = True
            first_line = read_first_line(daily_note_path)
            if first_line == f"# Daily Note — {today}":
                checks["daily_note_first_line"] = True
            # Contains "## Setup Day"
            if file_contains_line(daily_note_path, "## Setup Day"):
                checks["daily_note_setup_day"] = True

    # Cron schedule checks
    cron_path = os.path.join(ws_out, "cron_schedules.json")
    cron = read_json(cron_path)
    morning_ok = False
    nightly_ok = False
    if isinstance(cron, list) and len(cron) == 2:
        checks["cron_schedules_valid_length"] = True
        # Validate entries
        names = {item.get("name"): item for item in cron if isinstance(item, dict) and "name" in item}
        # Morning
        m = names.get("morning-daily-review")
        if m and isinstance(timezone, str) and isinstance(morning_hour, int):
            cron_str = m.get("cron")
            tz_val = m.get("tz")
            msg = m.get("message", "")
            expected_cron = f"0 {morning_hour} * * *"
            if cron_str == expected_cron and tz_val == timezone and "output/workspace/scripts/morning-daily-review.md" in msg:
                morning_ok = True
        # Nightly
        n = names.get("nightly-memory-consolidation")
        if n and isinstance(timezone, str) and isinstance(night_hour, int):
            cron_str = n.get("cron")
            tz_val = n.get("tz")
            msg = n.get("message", "")
            expected_cron = f"0 {night_hour} * * *"
            if cron_str == expected_cron and tz_val == timezone and "output/workspace/scripts/nightly-memory-consolidation.md" in msg:
                nightly_ok = True
    checks["cron_morning_valid"] = morning_ok
    checks["cron_nightly_valid"] = nightly_ok

    # Report checks
    report_path = os.path.join(output_dir, "report.json")
    report = read_json(report_path)
    if isinstance(report, dict):
        # presence and types
        created = report.get("created")
        dn_path = report.get("daily_note_path")
        sched_names = report.get("schedule_names")
        tz = report.get("timezone")
        hours = report.get("hours")
        valid_basic = (
            isinstance(created, dict)
            and isinstance(created.get("directories"), int)
            and isinstance(created.get("files"), int)
            and isinstance(dn_path, str)
            and isinstance(sched_names, list)
            and isinstance(tz, str)
            and isinstance(hours, dict)
            and isinstance(hours.get("morning"), int)
            and isinstance(hours.get("night"), int)
        )
        if valid_basic:
            checks["report_json_valid"] = True
            # counts match
            actual_dirs, actual_files = count_dirs_files(ws_out)
            if created.get("directories") == actual_dirs and created.get("files") == actual_files:
                checks["report_counts_match"] = True
            # daily note path match
            if isinstance(today, str):
                expected_dn_rel = f"output/workspace/memory/daily/{today}.md"
                if dn_path == expected_dn_rel:
                    checks["report_daily_note_path_match"] = True
            # timezone
            if isinstance(timezone, str) and tz == timezone:
                checks["report_timezone_match"] = True
            # hours
            if isinstance(morning_hour, int) and isinstance(night_hour, int):
                if hours.get("morning") == morning_hour and hours.get("night") == night_hour:
                    checks["report_hours_match"] = True
            # schedule names
            names_set = set(sched_names) if isinstance(sched_names, list) else set()
            if names_set == {"morning-daily-review", "nightly-memory-consolidation"} and len(sched_names) == 2:
                checks["report_schedule_names"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure reward is 0 if no artifact-dependent checks passed (no-op baseline)
    # This is already enforced by the calculation since passed would be 0.

    result = {"reward": round(reward, 6)}
    result.update(checks)
    # Print exactly one JSON object on the last non-empty line
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()