import json
import os
import sys
import re
from datetime import datetime

def is_numeric(v):
    return (isinstance(v, int) or isinstance(v, float)) and not isinstance(v, bool)

def is_date_str(s):
    if not isinstance(s, str):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f.readlines()]
    except Exception:
        return None

def validate_applications_updated(app_json):
    checks = {
        "applications_top_level_structure": False,
        "applications_stats_numeric_fields": False,
        "applications_items_structure_valid": False,
        "applications_has_interview_round": False,
    }

    if not isinstance(app_json, dict):
        return checks

    # Top-level keys and applications array length
    apps = app_json.get("applications")
    stats = app_json.get("stats")
    if isinstance(apps, list) and len(apps) >= 1 and isinstance(stats, dict):
        checks["applications_top_level_structure"] = True

    # Stats numeric fields
    if isinstance(stats, dict):
        required_stats = ["total_applied", "responses", "interviews", "offers", "response_rate"]
        if all(k in stats for k in required_stats) and all(is_numeric(stats[k]) for k in required_stats):
            checks["applications_stats_numeric_fields"] = True

    # Validate each application item fields and types
    items_valid = True
    has_interview_round = False
    if isinstance(apps, list) and len(apps) >= 1:
        for a in apps:
            if not isinstance(a, dict):
                items_valid = False
                break
            required_keys = ["id", "company", "role", "status", "applied_date", "follow_up_date", "interviews", "notes", "outcome"]
            if not all(k in a for k in required_keys):
                items_valid = False
                break
            if not all(isinstance(a[k], str) for k in ["id", "company", "role", "status"]):
                items_valid = False
                break
            # applied_date must be valid YYYY-MM-DD
            if not is_date_str(a["applied_date"]):
                items_valid = False
                break
            # follow_up_date string or null; if string, validate date
            fud = a["follow_up_date"]
            if not (fud is None or isinstance(fud, str)):
                items_valid = False
                break
            if isinstance(fud, str) and not is_date_str(fud):
                items_valid = False
                break
            # interviews array
            interviews = a["interviews"]
            if not isinstance(interviews, list):
                items_valid = False
                break
            # notes string or null
            notes = a["notes"]
            if not (notes is None or isinstance(notes, str)):
                items_valid = False
                break
            # outcome string or null
            outcome = a["outcome"]
            if not (outcome is None or isinstance(outcome, str)):
                items_valid = False
                break
            # track interview round presence
            if isinstance(interviews, list) and len(interviews) > 0:
                for iv in interviews:
                    if isinstance(iv, dict) and isinstance(iv.get("round"), str) and len(iv.get("round")) > 0:
                        has_interview_round = True
                        break
        if items_valid:
            checks["applications_items_structure_valid"] = True
        if has_interview_round:
            checks["applications_has_interview_round"] = True

    return checks

def validate_resume_tailoring(rt_json):
    checks = {
        "resume_keys_present_and_types": False,
        "resume_must_and_nice_not_empty": False,
        "resume_mapped_experience_items_valid": False,
        "resume_match_summary_numeric_fields": False,
    }

    if not isinstance(rt_json, dict):
        return checks

    must_have = rt_json.get("must_have")
    nice_to_have = rt_json.get("nice_to_have")
    mapped_experience = rt_json.get("mapped_experience")
    gaps = rt_json.get("gaps")
    match_summary = rt_json.get("match_summary")

    # Keys present and types
    if isinstance(must_have, list) and isinstance(nice_to_have, list) and isinstance(mapped_experience, list) and isinstance(gaps, list) and isinstance(match_summary, dict):
        checks["resume_keys_present_and_types"] = True

    # must_have and nice_to_have non-empty
    if isinstance(must_have, list) and len(must_have) >= 1 and isinstance(nice_to_have, list) and len(nice_to_have) >= 1:
        checks["resume_must_and_nice_not_empty"] = True

    # mapped_experience items
    valid_map = True
    if isinstance(mapped_experience, list):
        for item in mapped_experience:
            if not isinstance(item, dict):
                valid_map = False
                break
            if "requirement" not in item or "evidence" not in item:
                valid_map = False
                break
            if not isinstance(item["requirement"], str) or not isinstance(item["evidence"], str):
                valid_map = False
                break
    if valid_map and isinstance(mapped_experience, list):
        checks["resume_mapped_experience_items_valid"] = True

    # match_summary numeric fields
    if isinstance(match_summary, dict):
        req_fields = ["strong", "partial", "gaps"]
        if all(k in match_summary for k in req_fields) and all(is_numeric(match_summary[k]) for k in req_fields):
            checks["resume_match_summary_numeric_fields"] = True

    return checks

def validate_followups(f_json):
    checks = {
        "followups_drafts_array_present": False,
        "followups_draft_items_valid": False,
    }

    if not isinstance(f_json, dict):
        return checks

    drafts = f_json.get("drafts")
    if isinstance(drafts, list) and len(drafts) >= 1:
        checks["followups_drafts_array_present"] = True
        all_valid = True
        for d in drafts:
            if not isinstance(d, dict):
                all_valid = False
                break
            for key in ["company", "role", "subject", "body"]:
                if key not in d or not isinstance(d[key], str):
                    all_valid = False
                    break
            if not all_valid:
                break
            # body length >= 200 chars
            if len(d["body"]) < 200:
                all_valid = False
                break
        if all_valid:
            checks["followups_draft_items_valid"] = True

    return checks

def validate_report_md(lines):
    checks = {
        "report_contains_required_headings": False,
        "report_legacy_notice_includes_required_word": False,
    }

    if not isinstance(lines, list) or len(lines) == 0:
        return checks

    headings = ["Summary", "Data Sources", "Legacy Workflow Notice", "Next Actions"]
    # Find heading indices
    indices = {}
    for i, line in enumerate(lines):
        if line in headings and line not in indices:
            indices[line] = i

    if all(h in indices for h in headings):
        checks["report_contains_required_headings"] = True

        # Extract Legacy Workflow Notice section text until next heading or end
        legacy_idx = indices["Legacy Workflow Notice"]
        # determine next heading index after legacy
        next_indices = [idx for h, idx in indices.items() if idx > legacy_idx]
        end_idx = min(next_indices) if next_indices else len(lines)
        section_text = "\n".join(lines[legacy_idx + 1:end_idx])
        if re.search(r"\b(discontinued|retired)\b", section_text, flags=re.IGNORECASE):
            checks["report_legacy_notice_includes_required_word"] = True

    return checks

def validate_network_speed(lines):
    checks = {
        "network_speed_two_lines": False,
        "network_speed_format_valid": False,
    }
    if not isinstance(lines, list):
        return checks
    if len(lines) == 2:
        checks["network_speed_two_lines"] = True
        download_re = re.compile(r"^Download: \d+(\.\d{1,2})? Mbps$")
        upload_re = re.compile(r"^Upload:\s+\d+(\.\d{1,2})? Mbps$")
        if download_re.match(lines[0]) and upload_re.match(lines[1]):
            checks["network_speed_format_valid"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # applications_updated.json
        "has_applications_updated_json": False,
        "applications_top_level_structure": False,
        "applications_stats_numeric_fields": False,
        "applications_items_structure_valid": False,
        "applications_has_interview_round": False,
        # resume_tailoring.json
        "has_resume_tailoring_json": False,
        "resume_keys_present_and_types": False,
        "resume_must_and_nice_not_empty": False,
        "resume_mapped_experience_items_valid": False,
        "resume_match_summary_numeric_fields": False,
        # followups.json
        "has_followups_json": False,
        "followups_drafts_array_present": False,
        "followups_draft_items_valid": False,
        # report.md
        "has_report_md": False,
        "report_contains_required_headings": False,
        "report_legacy_notice_includes_required_word": False,
        # network_speed.txt
        "has_network_speed_txt": False,
        "network_speed_two_lines": False,
        "network_speed_format_valid": False,
    }

    # applications_updated.json
    app_path = os.path.join(output_dir, "applications_updated.json")
    app_json = load_json(app_path) if os.path.isfile(app_path) else None
    if app_json is not None:
        checks["has_applications_updated_json"] = True
        app_checks = validate_applications_updated(app_json)
        checks.update(app_checks)

    # resume_tailoring.json
    rt_path = os.path.join(output_dir, "resume_tailoring.json")
    rt_json = load_json(rt_path) if os.path.isfile(rt_path) else None
    if rt_json is not None:
        checks["has_resume_tailoring_json"] = True
        rt_checks = validate_resume_tailoring(rt_json)
        checks.update(rt_checks)

    # followups.json
    f_path = os.path.join(output_dir, "followups.json")
    f_json = load_json(f_path) if os.path.isfile(f_path) else None
    if f_json is not None:
        checks["has_followups_json"] = True
        f_checks = validate_followups(f_json)
        checks.update(f_checks)

    # report.md
    report_path = os.path.join(output_dir, "report.md")
    report_lines = read_text_lines(report_path) if os.path.isfile(report_path) else None
    if report_lines is not None:
        checks["has_report_md"] = True
        rep_checks = validate_report_md(report_lines)
        checks.update(rep_checks)

    # network_speed.txt
    ns_path = os.path.join(output_dir, "network_speed.txt")
    ns_lines = read_text_lines(ns_path) if os.path.isfile(ns_path) else None
    if ns_lines is not None:
        checks["has_network_speed_txt"] = True
        ns_checks = validate_network_speed(ns_lines)
        checks.update(ns_checks)

    # Compute reward: fraction of checks passed; ensure no-op baseline yields 0.0
    total_checks = len([k for k in checks.keys()])
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if passed > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()