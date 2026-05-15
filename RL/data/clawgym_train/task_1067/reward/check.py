import json
import os
import re
import sys
from datetime import datetime

def load_text(path):
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

def list_input_logs(input_dir):
    files = []
    if not os.path.isdir(input_dir):
        return files
    for name in os.listdir(input_dir):
        if name.lower().endswith(".txt"):
            files.append(os.path.join(input_dir, name))
    return sorted(files)

def compute_error_warning_counts(log_paths):
    # Patterns are case-insensitive. Count per-line occurrences (line counted at most once per category).
    error_re = re.compile(r'(ERROR|CRITICAL|FATAL|timeout|timed out|failed|failure|fail)', re.IGNORECASE)
    warn_re = re.compile(r'(WARN|WARNING|slow|performance)', re.IGNORECASE)

    errors = 0
    warnings = 0
    for p in log_paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line_stripped = line.rstrip("\n")
                    if error_re.search(line_stripped):
                        errors += 1
                    if warn_re.search(line_stripped):
                        warnings += 1
        except Exception:
            # If a file cannot be read, skip it (do not award credit for input reading itself)
            continue
    return errors, warnings

def compute_performance_metrics(log_paths):
    # Find lines with "duration" then number and unit (ms or s), case-insensitive.
    # Convert ms to seconds. Return (avg, max, min, count). If none, zeros.
    perf_re = re.compile(r'duration.*?(\d+(?:\.\d+)?)\s*(ms|s)\b', re.IGNORECASE)
    values_sec = []
    for p in log_paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    m = perf_re.search(line)
                    if m:
                        val = float(m.group(1))
                        unit = m.group(2).lower()
                        sec = val / 1000.0 if unit == "ms" else val
                        values_sec.append(sec)
        except Exception:
            continue
    if not values_sec:
        return 0.0, 0.0, 0.0, 0
    avg = sum(values_sec) / len(values_sec)
    mx = max(values_sec)
    mn = min(values_sec)
    return avg, mx, mn, len(values_sec)

def format_two_decimals(x):
    # Consistent formatting to two decimals with trailing zeros.
    return f"{round(x + 0.0, 2):.2f}"

def get_failed_jobs(cron_json_path):
    data = load_json(cron_json_path)
    failed = []
    if data is None:
        return failed
    jobs = []
    if isinstance(data, dict) and "jobs" in data and isinstance(data["jobs"], list):
        jobs = data["jobs"]
    elif isinstance(data, list):
        jobs = data
    else:
        # Unknown structure; no positive credit given for reading structure alone
        jobs = []

    for job in jobs:
        if not isinstance(job, dict):
            continue
        state = job.get("state") or {}
        last_status = state.get("lastStatus")
        if isinstance(last_status, str) and last_status.lower() == "error":
            name = job.get("name", "")
            last_err = state.get("lastError", "")
            failed.append({"name": name, "lastError": last_err})
    return failed

def extract_section(content, header):
    # Returns text between the header line and the next header (starting with "## ") or end of string.
    lines = content.splitlines()
    indices = [i for i, ln in enumerate(lines) if ln.strip() == header]
    if not indices:
        return None
    start = indices[0] + 1
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].strip().startswith("## ") and lines[i].strip() != header:
            end = i
            break
    return "\n".join(lines[start:end])

def parse_heading_number(content, heading_name):
    # Finds "## HeadingName (N)" and returns N as int
    pattern = re.compile(rf'^\s*##\s+{re.escape(heading_name)}\s*\((\d+)\)\s*$', re.MULTILINE)
    m = pattern.search(content)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def parse_performance_bullets(section_text):
    # Expects four bullets exactly:
    # - Average response time: X.YYs
    # - Maximum response time: X.YYs
    # - Minimum response time: X.YYs
    # - Total performance samples: K
    result = {
        "average": None,
        "maximum": None,
        "minimum": None,
        "total": None
    }
    if section_text is None:
        return result
    lines = [ln.strip() for ln in section_text.splitlines() if ln.strip()]
    avg_re = re.compile(r'^-\s+Average response time:\s+(\d+\.\d{2})s$')
    max_re = re.compile(r'^-\s+Maximum response time:\s+(\d+\.\d{2})s$')
    min_re = re.compile(r'^-\s+Minimum response time:\s+(\d+\.\d{2})s$')
    tot_re = re.compile(r'^-\s+Total performance samples:\s+(\d+)$')
    for ln in lines:
        m = avg_re.match(ln)
        if m:
            result["average"] = m.group(1)
            continue
        m = max_re.match(ln)
        if m:
            result["maximum"] = m.group(1)
            continue
        m = min_re.match(ln)
        if m:
            result["minimum"] = m.group(1)
            continue
        m = tot_re.match(ln)
        if m:
            result["total"] = int(m.group(1))
            continue
    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "status_file_valid": False,
        "status_counts_correct": False,
        "daily_report_exists_and_title": False,
        "daily_report_counts_match_status": False,
        "daily_report_failed_jobs_listed": False,
        "daily_report_performance_correct": False,
        "weekly_team_plan_valid": False,
        "prompt_weekly_summary_valid": False,
        "token_optimization_valid": False
    }

    # Compute expected values from inputs
    log_paths = list_input_logs(input_dir)
    computed_errors, computed_warnings = compute_error_warning_counts(log_paths)
    avg_sec, max_sec, min_sec, perf_count = compute_performance_metrics(log_paths)
    avg_s_str = format_two_decimals(avg_sec)
    max_s_str = format_two_decimals(max_sec)
    min_s_str = format_two_decimals(min_sec)
    failed_jobs = get_failed_jobs(os.path.join(input_dir, "cron_jobs.json"))
    failed_jobs_count = len(failed_jobs)

    # 1) Validate status.json
    status_path = os.path.join(output_dir, "status.json")
    status = load_json(status_path)
    if isinstance(status, dict):
        has_last_scan = isinstance(status.get("lastScan"), str)
        has_error_count = isinstance(status.get("errorCount"), int)
        has_warning_count = isinstance(status.get("warningCount"), int)
        has_failed_count = isinstance(status.get("failedTaskCount"), int)
        if has_last_scan and has_error_count and has_warning_count and has_failed_count:
            checks["status_file_valid"] = True
            if (status.get("errorCount") == computed_errors and
                status.get("warningCount") == computed_warnings and
                status.get("failedTaskCount") == failed_jobs_count):
                checks["status_counts_correct"] = True

    # 2) Validate daily_report.md
    daily_report_path = os.path.join(output_dir, "daily_report.md")
    daily_content = load_text(daily_report_path)
    if isinstance(daily_content, str):
        # Title must be the first line exactly
        lines = daily_content.splitlines()
        first_line = lines[0].strip() if lines else ""
        if first_line == "# Daily Log Analysis Report":
            checks["daily_report_exists_and_title"] = True

        # Counts headings must match status.json and computed values
        errors_heading_n = parse_heading_number(daily_content, "Errors")
        warnings_heading_m = parse_heading_number(daily_content, "Warnings")
        if (errors_heading_n is not None and warnings_heading_m is not None
            and status and isinstance(status, dict)
            and "errorCount" in status and "warningCount" in status):
            if (errors_heading_n == status.get("errorCount") == computed_errors and
                warnings_heading_m == status.get("warningCount") == computed_warnings):
                checks["daily_report_counts_match_status"] = True

        # Failed Jobs section must list each failed job name and its lastError
        failed_section = extract_section(daily_content, "## Failed Jobs")
        if failed_section is not None:
            all_listed = True
            for fj in failed_jobs:
                name = fj.get("name", "")
                err = fj.get("lastError", "")
                if (not name or name not in failed_section) or (err and err not in failed_section):
                    all_listed = False
                    break
            # If there are no failed jobs, still consider the section present as valid listing
            if all_listed:
                checks["daily_report_failed_jobs_listed"] = True

        # Performance metrics bullets
        perf_section = extract_section(daily_content, "## Performance Metrics")
        perf_parsed = parse_performance_bullets(perf_section)
        if (perf_parsed["average"] is not None and
            perf_parsed["maximum"] is not None and
            perf_parsed["minimum"] is not None and
            perf_parsed["total"] is not None):
            # Compare to computed (use two-decimal formatting)
            if (perf_parsed["average"] == avg_s_str and
                perf_parsed["maximum"] == max_s_str and
                perf_parsed["minimum"] == min_s_str and
                perf_parsed["total"] == perf_count):
                checks["daily_report_performance_correct"] = True

    # 3) Validate weekly_team_plan.json
    weekly_plan_path = os.path.join(output_dir, "weekly_team_plan.json")
    weekly_plan = load_json(weekly_plan_path)
    if isinstance(weekly_plan, dict):
        task_ok = isinstance(weekly_plan.get("task"), str) and weekly_plan.get("task") == "Weekly cron reliability remediation"
        mode_ok = isinstance(weekly_plan.get("mode"), str) and weekly_plan.get("mode") == "Sprint"
        team = weekly_plan.get("proposedTeam")
        exec_plan = weekly_plan.get("executionPlan")
        team_ok = False
        plan_ok = False
        if isinstance(team, list):
            # Build a lookup for role -> item
            role_map = {}
            for item in team:
                if isinstance(item, dict) and "role" in item:
                    role_map[item.get("role")] = item
            required_roles = [
                ("Leader", "CEO", "Core", "Phase 1"),
                ("Planner", "Senior PM", "Agency PM", "Phase 1"),
                ("Ops Automation", "DevOps Automator", "Agency Engineering", "Phase 2"),
                ("QA", "Evidence Collector", "Agency Testing", "Phase 3"),
                ("Gate", "Reality Checker", "Agency Testing", "Phase 3"),
            ]
            team_ok = True
            for role, agent, roster, phase in required_roles:
                it = role_map.get(role)
                if not it:
                    team_ok = False
                    break
                if it.get("agent") != agent or it.get("roster") != roster or it.get("phase") != phase:
                    team_ok = False
                    break
        if isinstance(exec_plan, list) and len(exec_plan) >= 3:
            # Must contain the three required plan items
            required_steps = [
                "Scope failure patterns and acceptance criteria",
                "Automate log parsing and alerting",
                "Run QA + final gate before rollout"
            ]
            plan_ok = all(step in exec_plan for step in required_steps)
        if task_ok and mode_ok and team_ok and plan_ok:
            checks["weekly_team_plan_valid"] = True

    # 4) Validate prompt_weekly_summary.md
    prompt_weekly_path = os.path.join(output_dir, "prompt_weekly_summary.md")
    prompt_content = load_text(prompt_weekly_path)
    if isinstance(prompt_content, str):
        headings_needed = [
            "# Weekly Log Summary Prompt",
            "## Objective",
            "## Instructions",
            "## Output Format",
            "## Examples",
            "## Quality Checks"
        ]
        has_all_headings = all(h in prompt_content for h in headings_needed)
        # Output Format section must mention JSON explicitly
        of_section = extract_section(prompt_content, "## Output Format")
        mentions_json = isinstance(of_section, str) and re.search(r'\bjson\b', of_section, re.IGNORECASE) is not None
        if has_all_headings and mentions_json:
            checks["prompt_weekly_summary_valid"] = True

    # 5) Validate token_optimization.json
    token_opt_path = os.path.join(output_dir, "token_optimization.json")
    token_opt = load_json(token_opt_path)
    if isinstance(token_opt, dict):
        baseline = token_opt.get("baseline")
        recs = token_opt.get("recommendations")
        baseline_ok = False
        recs_ok = False
        if isinstance(baseline, dict):
            keys = ["systemPromptTokens", "toolSchemaTokens", "workspaceTokens", "memoryTokens", "historyTokens"]
            types_ok = all(isinstance(baseline.get(k), (int, float)) for k in keys)
            # Ensure numeric values (allow int or float)
            baseline_ok = types_ok and all(k in baseline for k in keys)
        if isinstance(recs, list):
            expected_recs = [
                "trimWorkspaceFiles",
                "enablePromptCaching",
                "heartbeat",
                "contextPruning",
                "compaction",
                "subagents",
                "memorySearch",
                "cronAudit",
                "modelTiering"
            ]
            recs_ok = set(recs) == set(expected_recs) and len(recs) == len(expected_recs)
        if baseline_ok and recs_ok:
            checks["token_optimization_valid"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Print final JSON
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()