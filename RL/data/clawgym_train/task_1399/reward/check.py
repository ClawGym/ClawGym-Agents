import json
import os
import re
import sys

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

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "status_json_exists": False,
        "status_json_valid": False,
        "field_user_id_ok": False,
        "field_role_ok": False,
        "field_weeks_ok": False,
        "field_days_ok": False,
        "field_trimester_ok": False,
        "completed_contains_nt_scan": False,
        "custom_contains_infant_car_seat": False,
        "upcoming_anomaly_overdue": False,
        "upcoming_ogtt_upcoming": False,
        "upcoming_no_down_screening": False,
        "partner_md_exists": False,
        "partner_md_nonempty": False,
        "partner_md_contains_role_partner": False,
        "partner_md_contains_23_weeks": False,
        "partner_md_contains_safety_note": False,
    }

    # Paths
    status_path = os.path.join(output_dir, "status.json")
    partner_md_path = os.path.join(output_dir, "partner_summary.md")

    # Validate status.json
    if os.path.isfile(status_path):
        checks["status_json_exists"] = True
        status_obj = read_json(status_path)
        if isinstance(status_obj, dict):
            checks["status_json_valid"] = True

            # Required exact fields
            if status_obj.get("user_id") == "family_john":
                checks["field_user_id_ok"] = True
            if status_obj.get("role") == "partner":
                checks["field_role_ok"] = True
            if status_obj.get("weeks") == 23:
                checks["field_weeks_ok"] = True
            if status_obj.get("days") == 0:
                checks["field_days_ok"] = True
            if status_obj.get("trimester") == "second_trimester":
                checks["field_trimester_ok"] = True

            # completed_tasks must include "nt_scan"
            completed_tasks = status_obj.get("completed_tasks")
            if isinstance(completed_tasks, list) and "nt_scan" in completed_tasks:
                checks["completed_contains_nt_scan"] = True

            # custom_milestones must include {"title": "Buy infant car seat", "week": 28}
            custom_milestones = status_obj.get("custom_milestones")
            if isinstance(custom_milestones, list):
                for item in custom_milestones:
                    if isinstance(item, dict) and item.get("title") == "Buy infant car seat" and item.get("week") == 28:
                        checks["custom_contains_infant_car_seat"] = True
                        break

            # upcoming_tasks contains anomaly_scan overdue and ogtt upcoming
            # and must NOT include down_screening
            upcoming_tasks = status_obj.get("upcoming_tasks")
            if isinstance(upcoming_tasks, list):
                found_anomaly_overdue = False
                found_ogtt_upcoming = False
                found_down_screening = False
                for item in upcoming_tasks:
                    if not isinstance(item, dict):
                        continue
                    if item.get("id") == "anomaly_scan" and item.get("status") == "overdue":
                        found_anomaly_overdue = True
                    if item.get("id") == "ogtt" and item.get("status") == "upcoming":
                        found_ogtt_upcoming = True
                    if item.get("id") == "down_screening":
                        found_down_screening = True
                if found_anomaly_overdue:
                    checks["upcoming_anomaly_overdue"] = True
                if found_ogtt_upcoming:
                    checks["upcoming_ogtt_upcoming"] = True
                if not found_down_screening:
                    checks["upcoming_no_down_screening"] = True

    # Validate partner_summary.md
    if os.path.isfile(partner_md_path):
        checks["partner_md_exists"] = True
        md_text = read_text(partner_md_path)
        if md_text is not None and len(md_text.strip()) > 0:
            checks["partner_md_nonempty"] = True

            # Must contain "partner" (case-insensitive)
            if re.search(r"\bpartner\b", md_text, re.IGNORECASE):
                checks["partner_md_contains_role_partner"] = True

            # Must contain a reference to 23 weeks: "23 weeks" or "23w"
            if re.search(r"\b23\s*weeks\b", md_text, re.IGNORECASE) or re.search(r"\b23\s*w\b", md_text, re.IGNORECASE):
                checks["partner_md_contains_23_weeks"] = True

            # Must include safety note with either "not medical advice" or "consult a doctor" (case-insensitive)
            if re.search(r"not medical advice", md_text, re.IGNORECASE) or re.search(r"consult a doctor", md_text, re.IGNORECASE):
                checks["partner_md_contains_safety_note"] = True

    # Compute reward as fraction of passed checks; ensure 0.0 if no artifacts
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    # Explicit no-op baseline: if output is missing or empty, reward stays 0.0
    if checks["status_json_exists"] or checks["partner_md_exists"]:
        reward = passed / total if total > 0 else 0.0

    # Print final JSON (single line)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()