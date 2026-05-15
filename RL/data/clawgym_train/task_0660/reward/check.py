import json
import os
import sys
import re
from datetime import datetime

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_jsonl(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    lines.append(obj)
                except Exception:
                    # Non-parseable line
                    lines.append(None)
        return lines
    except Exception:
        return None

def has_required_keys(obj, keys):
    if not isinstance(obj, dict):
        return False
    for k in keys:
        if k not in obj:
            return False
    return True

def text_contains_one_service_down(text):
    if not isinstance(text, str):
        return False
    # Look for explicit "1 service down" or "services down: 1" or similar phrasing
    patterns = [
        r"(?i)\b1 service down\b",
        r"(?i)\bservices down:\s*1\b",
        r"(?i)\bservice\(s\)\s+down\b.*\b1\b",
        r"(?i)\bservices\s+down\b.*\b1\b",
    ]
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False

def incident_match(objs, category, severity, substrings_any=None, substrings_all=None):
    substrings_any = substrings_any or []
    substrings_all = substrings_all or []
    for obj in objs:
        if not isinstance(obj, dict):
            continue
        if obj.get("category") != category or obj.get("severity") != severity:
            continue
        title = str(obj.get("title", "")).lower()
        detail = str(obj.get("detail", "")).lower()
        blob = title + " " + detail
        # all substrings must be present
        if not all(s.lower() in blob for s in substrings_all):
            continue
        # at least one of any substrings present (if provided)
        if substrings_any:
            if not any(s.lower() in blob for s in substrings_any):
                continue
        return True
    return False

def problem_match(objs, severity, substrings_all=None, substrings_any=None):
    substrings_all = substrings_all or []
    substrings_any = substrings_any or []
    for obj in objs:
        if not isinstance(obj, dict):
            continue
        if obj.get("severity") != severity:
            continue
        title = str(obj.get("title", "")).lower()
        detail = str(obj.get("detail", "")).lower()
        blob = title + " " + detail
        if not all(s.lower() in blob for s in substrings_all):
            continue
        if substrings_any:
            if not any(s.lower() in blob for s in substrings_any):
                continue
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Report checks
        "report_exists": False,
        "report_counts_line": False,
        "report_snapshot_values": False,
        # State checks
        "state_exists": False,
        "state_valid_json": False,
        "state_values_ok": False,
        # Incidents checks
        "incidents_exists": False,
        "incidents_min_lines": False,
        "incidents_all_lines_keys": False,
        "incident_mem_p1_ram_92": False,
        "incident_disk_p3_88": False,
        "incident_cron_p3_indexer_3": False,
        "incident_mem_p3_broken": False,
        "incident_service_p4_skchat_or_down": False,
        # Problems checks
        "problems_exists": False,
        "problems_min_lines": False,
        "problems_all_lines_keys": False,
        "problem_p1_skcapstone_crash_loop": False,
        "problem_p2_cron_daily_report_5": False,
        "problem_p2_recurring_phrase": False,
    }

    # Paths
    report_path = os.path.join(output_dir, "itil", "report.md")
    state_path = os.path.join(output_dir, "itil", "itil-state.json")
    incidents_path = os.path.join(output_dir, "itil", "tickets", "incidents.jsonl")
    problems_path = os.path.join(output_dir, "itil", "tickets", "problems.jsonl")

    # 1) Report file validations
    report_text = read_text(report_path)
    if report_text is not None:
        checks["report_exists"] = True
        # exact phrase
        if "Found 5 incident(s) and 3 problem(s)" in report_text:
            checks["report_counts_line"] = True
        # snapshot values: "88%" and "92%" and indicates exactly 1 service down
        has_88 = "88%" in report_text
        has_92 = "92%" in report_text
        has_1_down = text_contains_one_service_down(report_text)
        if has_88 and has_92 and has_1_down:
            checks["report_snapshot_values"] = True

    # 2) State file validations
    state_obj = None
    if os.path.isfile(state_path):
        checks["state_exists"] = True
        state_obj = read_json(state_path)
        if isinstance(state_obj, dict):
            checks["state_valid_json"] = True
            last_review = state_obj.get("last_review", "")
            last_incident_count = state_obj.get("last_incident_count")
            last_problem_count = state_obj.get("last_problem_count")
            disk_pct = state_obj.get("disk_pct")
            ram_used_pct = state_obj.get("ram_used_pct")
            services_down = state_obj.get("services_down")
            if (
                isinstance(last_review, str) and len(last_review.strip()) > 0 and
                last_incident_count == 5 and
                last_problem_count == 3 and
                disk_pct == 88 and
                ram_used_pct == 92 and
                services_down == 1
            ):
                checks["state_values_ok"] = True

    # 3) Incident tickets validations
    incidents_list = read_jsonl(incidents_path)
    required_keys = ["severity", "category", "title", "detail", "impact", "action", "detected"]
    if isinstance(incidents_list, list):
        checks["incidents_exists"] = True
        non_empty_lines = incidents_list
        parseable_count = sum(1 for obj in non_empty_lines if isinstance(obj, dict))
        # At least 5 JSON lines
        if parseable_count >= 5:
            checks["incidents_min_lines"] = True
        # Each line must be parseable and include all required keys
        if len(non_empty_lines) > 0 and all(isinstance(obj, dict) for obj in non_empty_lines):
            if all(has_required_keys(obj, required_keys) for obj in non_empty_lines):
                checks["incidents_all_lines_keys"] = True

        # Content checks
        # Memory P1 RAM 92%
        checks["incident_mem_p1_ram_92"] = incident_match(
            non_empty_lines,
            category="memory",
            severity="P1",
            substrings_all=["ram", "92%"]
        )
        # Disk P3 88%
        checks["incident_disk_p3_88"] = incident_match(
            non_empty_lines,
            category="disk",
            severity="P3",
            substrings_all=["88%"]
        )
        # Cron P3 indexer 3 consecutive failures
        checks["incident_cron_p3_indexer_3"] = incident_match(
            non_empty_lines,
            category="cron",
            severity="P3",
            substrings_all=["indexer", "3", "consecutive"]
        )
        # Memory P3 broken memory or content=dict
        checks["incident_mem_p3_broken"] = incident_match(
            non_empty_lines,
            category="memory",
            severity="P3",
            substrings_any=["broken memory", "content=dict"]
        )
        # Service P4 skchat or service(s) down
        checks["incident_service_p4_skchat_or_down"] = incident_match(
            non_empty_lines,
            category="service",
            severity="P4",
            substrings_any=["skchat", "service(s) down", "services down", "service down", "down"]
        )

    # 4) Problem tickets validations
    problems_list = read_jsonl(problems_path)
    if isinstance(problems_list, list):
        checks["problems_exists"] = True
        non_empty_lines_p = problems_list
        parseable_count_p = sum(1 for obj in non_empty_lines_p if isinstance(obj, dict))
        if parseable_count_p >= 3:
            checks["problems_min_lines"] = True
        if len(non_empty_lines_p) > 0 and all(isinstance(obj, dict) for obj in non_empty_lines_p):
            if all(has_required_keys(obj, required_keys) for obj in non_empty_lines_p):
                checks["problems_all_lines_keys"] = True

        # P1 skcapstone crash loop
        checks["problem_p1_skcapstone_crash_loop"] = problem_match(
            non_empty_lines_p,
            severity="P1",
            substrings_all=["skcapstone", "crash loop"]
        )
        # P2 cron daily-report 5 consecutive failures
        checks["problem_p2_cron_daily_report_5"] = problem_match(
            non_empty_lines_p,
            severity="P2",
            substrings_all=["daily-report", "5", "consecutive"],
            substrings_any=["cron"]
        )
        # P2 recurring incidents across review periods
        checks["problem_p2_recurring_phrase"] = problem_match(
            non_empty_lines_p,
            severity="P2",
            substrings_all=["recurring incidents across review periods"]
        )

    # Compute reward: ratio of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # No-op baseline: if output directory missing or none of the required files exist, reward = 0.0
    required_paths_exist = any(os.path.isfile(p) for p in [report_path, state_path, incidents_path, problems_path])
    if not required_paths_exist:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()