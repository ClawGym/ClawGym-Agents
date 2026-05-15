import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def section_text(full_text, start_marker, next_markers):
    """Extract text of a section starting at start_marker until the next of next_markers or end."""
    if full_text is None:
        return ""
    start_idx = full_text.find(start_marker)
    if start_idx == -1:
        return ""
    # Find next section marker
    next_idx = len(full_text)
    for nm in next_markers:
        idx = full_text.find(nm, start_idx + len(start_marker))
        if idx != -1 and idx < next_idx:
            next_idx = idx
    return full_text[start_idx:next_idx]

def line_contains_both(text, name, indicator):
    if text is None:
        return False
    for line in text.splitlines():
        if name in line and indicator in line:
            return True
    return False

def contains_name_in_segment(file_text, section_header, names):
    seg = section_text(file_text, section_header, ["## Active Projects", "## On Hold", "## Completed"])
    results = {}
    for n in names:
        results[n] = (n in seg)
    return results

def has_priority_line(text):
    if text is None:
        return False
    # Look for a line containing "Priority:" and P1/P2/P3
    for line in text.splitlines():
        if "Priority:" in line and any(p in line for p in ["P1", "P2", "P3"]):
            return True
    return False

def has_status_emoji(text, expected_label):
    if text is None:
        return False
    # Check that the expected emoji+label appears anywhere
    return expected_label in text

def has_section(text, header):
    if text is None:
        return False
    return header in text

def weekly_contains_after_label(text, label, required_strings):
    """Find label occurrence and check that within the next few lines or characters, required_strings appear."""
    if text is None:
        return False
    idx = text.find(label)
    if idx == -1:
        return False
    # Take the subsequent 500 characters for a simple heuristic
    window = text[idx: idx + 1000]
    return all(rs in window for rs in required_strings)

def recommendations_contains(text, project_name):
    if text is None:
        return False
    # Find recommendations section
    seg = section_text(text, "## Recommendations", ["## ", "# "])
    if not seg:
        # If not found, just search whole text as fallback
        seg = text
    # Check if there is a line in seg containing the project name and either 'pause' or 'kill'
    for line in seg.splitlines():
        if project_name in line and (("pause" in line.lower()) or ("kill" in line.lower())):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    projects_dir = os.path.join(output_dir, "projects")
    dashboard_path = os.path.join(projects_dir, "DASHBOARD.md")
    weekly_path = os.path.join(projects_dir, "weekly", "weekly_review_2026-04-13_to_2026-04-19.md")

    # Dashboard checks
    checks["dashboard_exists"] = os.path.isfile(dashboard_path)
    dashboard_text = read_text(dashboard_path) if checks["dashboard_exists"] else None

    checks["dashboard_last_updated_line"] = False
    checks["dashboard_table_header"] = False
    checks["dashboard_has_active_section"] = False
    checks["dashboard_has_on_hold_section"] = False
    checks["dashboard_has_completed_section"] = False

    if dashboard_text:
        checks["dashboard_last_updated_line"] = ("Last updated: 2026-04-20" in dashboard_text)
        checks["dashboard_table_header"] = ("| Project | Status | Priority | Next Action | Due |" in dashboard_text)
        checks["dashboard_has_active_section"] = ("## Active Projects" in dashboard_text)
        checks["dashboard_has_on_hold_section"] = ("## On Hold" in dashboard_text)
        checks["dashboard_has_completed_section"] = ("## Completed" in dashboard_text)

    # Check project names under sections
    active_names = ["Website Redesign", "Data Pipeline Revamp", "Mobile App v2", "SEO Content Series"]
    on_hold_names = ["Newsletter Automation"]
    completed_names = ["Legacy Feature Deprecation"]

    checks["dashboard_active_contains_website_redesign"] = False
    checks["dashboard_active_contains_data_pipeline_revamp"] = False
    checks["dashboard_active_contains_mobile_app_v2"] = False
    checks["dashboard_active_contains_seo_content_series"] = False
    checks["dashboard_on_hold_contains_newsletter_automation"] = False
    checks["dashboard_completed_contains_legacy_feature_deprecation"] = False

    if dashboard_text:
        act_results = contains_name_in_segment(dashboard_text, "## Active Projects", active_names)
        checks["dashboard_active_contains_website_redesign"] = act_results.get("Website Redesign", False)
        checks["dashboard_active_contains_data_pipeline_revamp"] = act_results.get("Data Pipeline Revamp", False)
        checks["dashboard_active_contains_mobile_app_v2"] = act_results.get("Mobile App v2", False)
        checks["dashboard_active_contains_seo_content_series"] = act_results.get("SEO Content Series", False)

        on_results = contains_name_in_segment(dashboard_text, "## On Hold", on_hold_names)
        checks["dashboard_on_hold_contains_newsletter_automation"] = on_results.get("Newsletter Automation", False)

        comp_results = contains_name_in_segment(dashboard_text, "## Completed", completed_names)
        checks["dashboard_completed_contains_legacy_feature_deprecation"] = comp_results.get("Legacy Feature Deprecation", False)

    # Stalled indicators in dashboard per stalled project
    stalled_projects = ["Data Pipeline Revamp", "Newsletter Automation", "SEO Content Series"]
    for sp in stalled_projects:
        key = f"dashboard_stalled_indicator_for_{sp.lower().replace(' ', '_').replace('-', '_')}"
        checks[key] = False
        if dashboard_text:
            checks[key] = line_contains_both(dashboard_text, sp, "⚠️ Stalled")

    # Individual project files
    project_files = {
        "website-redesign": {
            "path": os.path.join(projects_dir, "website-redesign.md"),
            "status": "🟢 Active",
            "priority_score": "4.30",
        },
        "data-pipeline-revamp": {
            "path": os.path.join(projects_dir, "data-pipeline-revamp.md"),
            "status": "🟢 Active",
            "priority_score": "3.80",
        },
        "newsletter-automation": {
            "path": os.path.join(projects_dir, "newsletter-automation.md"),
            "status": "🟡 On Hold",
            "priority_score": "2.35",
        },
        "mobile-app-v2": {
            "path": os.path.join(projects_dir, "mobile-app-v2.md"),
            "status": "🟢 Active",
            "priority_score": "2.30",
        },
        "legacy-feature-deprecation": {
            "path": os.path.join(projects_dir, "legacy-feature-deprecation.md"),
            "status": "✅ Done",
            "priority_score": "2.05",
        },
        "seo-content-series": {
            "path": os.path.join(projects_dir, "seo-content-series.md"),
            "status": "🟢 Active",
            "priority_score": "2.95",
        },
    }

    for slug, info in project_files.items():
        exists_key = f"{slug}_file_exists"
        checks[exists_key] = os.path.isfile(info["path"])
        text = read_text(info["path"]) if checks[exists_key] else None

        status_key = f"{slug}_status_line_ok"
        priority_line_key = f"{slug}_priority_line_present"
        score_key = f"{slug}_priority_score_value_ok"
        milestones_key = f"{slug}_milestones_section"
        progress_key = f"{slug}_progress_log_section"
        stalled_note_key = f"{slug}_stalled_note_present"

        checks[status_key] = has_status_emoji(text, info["status"]) if text else False
        checks[priority_line_key] = has_priority_line(text) if text else False
        checks[score_key] = (f"Priority Score: {info['priority_score']}" in text) if text else False
        checks[milestones_key] = has_section(text, "## Milestones") if text else False
        checks[progress_key] = has_section(text, "## Progress Log") if text else False

        # Only required for stalled projects
        if slug in ["data-pipeline-revamp", "newsletter-automation", "seo-content-series"]:
            checks[stalled_note_key] = ("⚠️ Stalled" in text) if text else False
        else:
            # For non-stalled, do not require presence; mark as True to avoid penalizing
            # but to avoid awarding credit without dependency, we will not include non-stalled stalled_note in scoring by setting to False but not counting it.
            checks[stalled_note_key] = True  # neutral, will not be part of scoring explicitly

    # Weekly review checks
    checks["weekly_exists"] = os.path.isfile(weekly_path)
    weekly_text = read_text(weekly_path) if checks["weekly_exists"] else None

    checks["weekly_title_ok"] = False
    checks["weekly_active_count_line"] = False
    checks["weekly_completed_contains_legacy"] = False
    checks["weekly_stalled_list_contains_all"] = False
    checks["weekly_recommendations_include_newsletter_pause_kill"] = False
    checks["weekly_recommendations_include_mobile_pause_kill"] = False

    if weekly_text:
        checks["weekly_title_ok"] = ("# Weekly Project Review — 2026-04-13 to 2026-04-19" in weekly_text)
        checks["weekly_active_count_line"] = ("Active: 4 projects" in weekly_text)
        # Check Completed this week includes Legacy Feature Deprecation near the label
        checks["weekly_completed_contains_legacy"] = weekly_contains_after_label(
            weekly_text, "Completed this week", ["Legacy Feature Deprecation"]
        )
        # Stalled list includes the three projects
        checks["weekly_stalled_list_contains_all"] = weekly_contains_after_label(
            weekly_text, "Stalled", ["Data Pipeline Revamp", "Newsletter Automation", "SEO Content Series"]
        )
        # Recommendations include pause/kill suggestions for Newsletter Automation and Mobile App v2
        checks["weekly_recommendations_include_newsletter_pause_kill"] = recommendations_contains(weekly_text, "Newsletter Automation")
        checks["weekly_recommendations_include_mobile_pause_kill"] = recommendations_contains(weekly_text, "Mobile App v2")

    # Compute reward: fraction of checks passed among the ones that represent concrete validation points
    # Define which checks count towards scoring
    scoring_keys = []

    # Dashboard scoring keys
    scoring_keys += [
        "dashboard_exists",
        "dashboard_last_updated_line",
        "dashboard_table_header",
        "dashboard_has_active_section",
        "dashboard_has_on_hold_section",
        "dashboard_has_completed_section",
        "dashboard_active_contains_website_redesign",
        "dashboard_active_contains_data_pipeline_revamp",
        "dashboard_active_contains_mobile_app_v2",
        "dashboard_active_contains_seo_content_series",
        "dashboard_on_hold_contains_newsletter_automation",
        "dashboard_completed_contains_legacy_feature_deprecation",
        "dashboard_stalled_indicator_for_data_pipeline_revamp",
        "dashboard_stalled_indicator_for_newsletter_automation",
        "dashboard_stalled_indicator_for_seo_content_series",
    ]

    # Project file scoring keys
    for slug in project_files.keys():
        scoring_keys.append(f"{slug}_file_exists")
        scoring_keys.append(f"{slug}_status_line_ok")
        scoring_keys.append(f"{slug}_priority_line_present")
        scoring_keys.append(f"{slug}_priority_score_value_ok")
        scoring_keys.append(f"{slug}_milestones_section")
        scoring_keys.append(f"{slug}_progress_log_section")
    # Stalled note only for stalled projects
    scoring_keys.append("data-pipeline-revamp_stalled_note_present")
    scoring_keys.append("newsletter-automation_stalled_note_present")
    scoring_keys.append("seo-content-series_stalled_note_present")

    # Weekly scoring keys
    scoring_keys += [
        "weekly_exists",
        "weekly_title_ok",
        "weekly_active_count_line",
        "weekly_completed_contains_legacy",
        "weekly_stalled_list_contains_all",
        "weekly_recommendations_include_newsletter_pause_kill",
        "weekly_recommendations_include_mobile_pause_kill",
    ]

    # Ensure keys exist in checks
    scoring_keys = [k for k in scoring_keys if k in checks]

    total = len(scoring_keys)
    passed = sum(1 for k in scoring_keys if checks.get(k, False))

    # No-op baseline: if output directory missing or empty of required artifacts (none of the main files exist), reward = 0.0
    if not os.path.isdir(output_dir) or not any([checks.get("dashboard_exists", False), checks.get("weekly_exists", False)] + [checks.get(f"{slug}_file_exists", False) for slug in project_files.keys()]):
        reward = 0.0
    else:
        reward = (passed / total) if total > 0 else 0.0

    # Clamp reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    # Print exactly one JSON object
    result = {"reward": reward}
    # Add all checks
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()