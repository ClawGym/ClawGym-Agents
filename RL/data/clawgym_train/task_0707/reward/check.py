import json
import os
import sys
from datetime import datetime, date

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_string(x):
    return isinstance(x, str)

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def contains_case_insensitive(haystack, needle):
    return needle.lower() in haystack.lower()

def line_has_heading(lines, text):
    # Check for markdown headings like "# About Me", "## About Me", etc.
    target = text.lower()
    for ln in lines:
        s = ln.strip()
        if s.startswith("#"):
            # remove leading hashes and spaces
            while s.startswith("#"):
                s = s[1:]
            s = s.strip()
            if s.lower() == target:
                return True
    return False

def step_names_cover_required(steps):
    # Flexible matching for required phases
    required = {
        "setup_memory": False,
        "weekly_maintenance": False,
        "marketing_analysis": False,
        "linter": False,
        "finalize": False,
    }
    for step in steps:
        name = step.get("name", "")
        if not isinstance(name, str):
            continue
        n = name.strip().lower()
        # Setup memory
        if ("setup" in n or "initialize" in n or "init" in n) and "memory" in n:
            required["setup_memory"] = True
        # Weekly maintenance
        if "maintenance" in n or ("weekly" in n and ("memory" in n or "review" in n)):
            required["weekly_maintenance"] = True
        # Marketing analysis
        if "marketing" in n and ("analysis" in n or "strategy" in n):
            required["marketing_analysis"] = True
        # Linter
        if "linter" in n or "lint" in n or "link validation" in n or "validator" in n:
            required["linter"] = True
        # Finalize deliverables
        if "finalize" in n or "finalise" in n or "deliverable" in n or ("final" in n and "deliver" in n):
            required["finalize"] = True
    return all(required.values())

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "memory_md_exists": False,
        "memory_md_has_headings": False,
        "memory_md_has_privacy_note": False,
        "memory_md_no_sensitive_tokens": False,

        "daily_log_exists": False,
        "daily_log_contains_refs": False,

        "agents_md_exists": False,
        "agents_md_has_memory_system": False,

        "heartbeat_md_exists": False,
        "heartbeat_md_has_memory_maintenance": False,

        "maintenance_report_exists": False,
        "maintenance_report_sections": False,

        "analysis_json_exists": False,
        "analysis_json_valid_schema": False,

        "campaign_plan_exists": False,
        "campaign_plan_valid_schema": False,

        "lint_report_exists": False,
        "lint_report_valid_schema": False,
        "lint_report_sufficient_files": False,
        "lint_report_no_broken_links": False,

        "progress_json_exists": False,
        "progress_json_valid_schema": False,
        "progress_json_status_done": False,
        "progress_json_steps_count": False,
        "progress_json_steps_cover_required": False,
    }

    # Paths
    memory_md_path = os.path.join(output_dir, "MEMORY.md")
    agents_md_path = os.path.join(output_dir, "AGENTS.md")
    heartbeat_md_path = os.path.join(output_dir, "HEARTBEAT.md")
    maintenance_report_path = os.path.join(output_dir, "maintenance_report.md")
    marketing_analysis_path = os.path.join(output_dir, "marketing", "analysis.json")
    campaign_plan_path = os.path.join(output_dir, "marketing", "campaign_plan.json")
    lint_report_path = os.path.join(output_dir, "lint_report.json")
    progress_json_path = os.path.join(output_dir, "tasks", "progress.json")

    # Today daily log path
    today_str = date.today().strftime("%Y-%m-%d")
    today_log_path = os.path.join(output_dir, "memory", f"{today_str}.md")

    # MEMORY.md checks
    if os.path.isfile(memory_md_path):
        checks["memory_md_exists"] = True
        content = read_text(memory_md_path) or ""
        lines = content.splitlines()

        # Headings: About Me, Key Decisions, Lessons Learned, Important Context
        headings_required = ["About Me", "Key Decisions", "Lessons Learned", "Important Context"]
        has_all = True
        for h in headings_required:
            if not (line_has_heading(lines, h) or contains_case_insensitive(content, h)):
                has_all = False
                break
        checks["memory_md_has_headings"] = has_all

        # Privacy note: mention that MEMORY.md should be private
        # Require both "private" and "MEMORY.md" present (case-insensitive)
        if content:
            has_private = "private" in content.lower()
            has_memory_md = "memory.md" in content.lower()
            checks["memory_md_has_privacy_note"] = bool(has_private and has_memory_md)

        # No sensitive tokens: must NOT include "password" or "token" (case-insensitive)
        lc = content.lower()
        if ("password" in lc) or ("token" in lc):
            checks["memory_md_no_sensitive_tokens"] = False
        else:
            checks["memory_md_no_sensitive_tokens"] = True

    # Daily log checks
    if os.path.isfile(today_log_path):
        checks["daily_log_exists"] = True
        dl_content = read_text(today_log_path) or ""
        # Must contain date string and at least one of: "memory", "log", "maintenance"
        has_date = today_str in dl_content
        lc = dl_content.lower()
        has_ref = ("memory" in lc) or ("log" in lc) or ("maintenance" in lc)
        checks["daily_log_contains_refs"] = bool(has_date and has_ref)

    # AGENTS.md checks
    if os.path.isfile(agents_md_path):
        checks["agents_md_exists"] = True
        c = read_text(agents_md_path) or ""
        checks["agents_md_has_memory_system"] = "memory system" in (c.lower())

    # HEARTBEAT.md checks
    if os.path.isfile(heartbeat_md_path):
        checks["heartbeat_md_exists"] = True
        c = read_text(heartbeat_md_path) or ""
        checks["heartbeat_md_has_memory_maintenance"] = "memory maintenance" in (c.lower())

    # maintenance_report.md checks
    if os.path.isfile(maintenance_report_path):
        checks["maintenance_report_exists"] = True
        c = read_text(maintenance_report_path) or ""
        checks["maintenance_report_sections"] = ("integrated" in c.lower() and "not kept" in c.lower())

    # marketing/analysis.json checks
    if os.path.isfile(marketing_analysis_path):
        checks["analysis_json_exists"] = True
        data = load_json(marketing_analysis_path)
        if isinstance(data, dict):
            has_id = is_string(data.get("analysis_id", "")) and len(data.get("analysis_id", "")) > 0
            mo = data.get("market_opportunities")
            ts = data.get("target_segments")
            ra = data.get("recommended_actions")
            rk = data.get("risks")
            ns = data.get("next_steps")
            cl = data.get("confidence_level")
            mo_valid = isinstance(mo, list) and len(mo) >= 1
            ts_valid = isinstance(ts, list)
            ra_valid = isinstance(ra, list)
            rk_valid = isinstance(rk, list)
            ns_valid = isinstance(ns, list)
            cl_valid = is_number(cl) and 0 <= float(cl) <= 100
            if has_id and mo_valid and ts_valid and ra_valid and rk_valid and ns_valid and cl_valid:
                checks["analysis_json_valid_schema"] = True

    # marketing/campaign_plan.json checks
    if os.path.isfile(campaign_plan_path):
        checks["campaign_plan_exists"] = True
        data = load_json(campaign_plan_path)
        valid = False
        if isinstance(data, dict):
            tasks = data.get("tasks")
            if isinstance(tasks, list) and len(tasks) >= 1:
                all_ok = True
                for t in tasks:
                    if not isinstance(t, dict):
                        all_ok = False
                        break
                    name = t.get("name")
                    owner = t.get("owner")
                    deadline = t.get("deadline")
                    expected = t.get("expected_result")
                    if not (is_string(name) and is_string(owner) and is_string(deadline) and is_string(expected)):
                        all_ok = False
                        break
                    # Optional status allowed; if present, ensure it is string
                    if "status" in t and not is_string(t.get("status")):
                        all_ok = False
                        break
                valid = all_ok
        checks["campaign_plan_valid_schema"] = valid

    # lint_report.json checks
    if os.path.isfile(lint_report_path):
        checks["lint_report_exists"] = True
        data = load_json(lint_report_path)
        if isinstance(data, dict):
            tf = data.get("totalFiles")
            blc = data.get("brokenLinksCount")
            details = data.get("details")
            schema_ok = is_number(tf) and is_number(blc) and isinstance(details, list)
            checks["lint_report_valid_schema"] = schema_ok
            if schema_ok:
                if float(tf) >= 5:
                    checks["lint_report_sufficient_files"] = True
                if float(blc) == 0:
                    checks["lint_report_no_broken_links"] = True

    # tasks/progress.json checks
    if os.path.isfile(progress_json_path):
        checks["progress_json_exists"] = True
        data = load_json(progress_json_path)
        schema_ok = False
        status_done_ok = False
        steps_count_ok = False
        steps_cover_ok = False
        if isinstance(data, dict):
            task_id = data.get("taskId")
            task_name = data.get("taskName")
            status = data.get("status")
            started = data.get("startedAt")
            updated = data.get("updatedAt")
            finished = data.get("finishedAt")
            steps = data.get("steps")
            base_ok = (is_string(task_id) and is_string(task_name) and is_string(status)
                       and is_string(started) and is_string(updated) and is_string(finished)
                       and isinstance(steps, list))
            if base_ok:
                allowed_statuses = {"pending", "running", "done"}
                per_step_ok = True
                for s in steps:
                    if not isinstance(s, dict):
                        per_step_ok = False
                        break
                    if not is_string(s.get("name")):
                        per_step_ok = False
                        break
                    st = s.get("status")
                    if (not is_string(st)) or (st not in allowed_statuses):
                        per_step_ok = False
                        break
                schema_ok = per_step_ok
                steps_count_ok = len(steps) >= 5
                steps_cover_ok = step_names_cover_required(steps)
                status_done_ok = (status == "done")
        checks["progress_json_valid_schema"] = schema_ok
        checks["progress_json_status_done"] = status_done_ok
        checks["progress_json_steps_count"] = steps_count_ok
        checks["progress_json_steps_cover_required"] = steps_cover_ok

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object on the last non-empty line
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()