import json
import os
import re
import sys
from collections import OrderedDict

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def norm(s):
    return (s or "").strip()

def contains_ci(haystack, needle):
    return needle.lower() in haystack.lower()

def get_pref(data, *keys):
    # Try multiple key variants; return None if not found
    if not isinstance(data, dict):
        return None
    # Pre-normalize map for space/dash/underscore/camelCase variations
    def variants(k):
        v = [k, k.replace(" ", "_"), k.replace("_", " "), k.replace("-", "_"), k.replace("_", "-")]
        # camelCase candidates
        parts = re.split(r"[ _\-]", k)
        camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
        v.append(camel)
        return list(dict.fromkeys(v))
    for k in keys:
        for v in variants(k):
            if v in data:
                return data[v]
    return None

def parse_skills_md(text):
    # Parse a simple ledger where entries are blocks containing keys like 'slug:', 'location:', etc.
    entries = {}
    current_slug = None
    for line in text.splitlines():
        l = line.strip()
        if not l:
            continue
        # remove leading bullet dash if present
        if l.startswith("- "):
            l = l[2:].strip()
        m = re.match(r"(?i)\bslug\s*:\s*(.+)$", l)
        if m:
            current_slug = m.group(1).strip()
            entries[current_slug] = {}
            entries[current_slug]["slug"] = current_slug
            continue
        if current_slug:
            m2 = re.match(r"(?i)\b(location|installed[_ ]version|auto[_ ]update|last[_ ]backup|migration[_ ]state)\s*:\s*(.*)$", l)
            if m2:
                key = m2.group(1).lower().replace(" ", "_")
                val = m2.group(2).strip()
                entries[current_slug][key] = val
    return entries

def extract_section(text, header):
    # Return the substring of text starting at header (case-insensitive) until next '## ' header or end
    pattern = re.compile(rf"(?mi)^##\s*{re.escape(header)}\s*$")
    m = pattern.search(text)
    if not m:
        return ""
    start = m.end()
    m_next = re.search(r"(?m)^##\s+.*$", text[start:])
    if m_next:
        end = start + m_next.start()
    else:
        end = len(text)
    return text[start:end]

def parse_mode_from_core(text):
    # Look for 'Mode: <value>'
    m = re.search(r"(?mi)^\s*Mode\s*:\s*([a-zA-Z\-]+)\s*$", text)
    if m:
        return m.group(1).strip().lower()
    return None

def has_backup_scope_in_core(text):
    # Look for a line containing "Backup" and "scope"
    for line in text.splitlines():
        low = line.lower()
        if "backup" in low and "scope" in low:
            return True
    return False

def feature_review_value_in_core(text):
    # Detect feature review line with yes/no
    m = re.search(r"(?mi)^\s*(Post[- ]?update\s+feature\s+review|Feature\s+review)\s*:\s*(yes|no)\s*$", text)
    if m:
        return m.group(2).strip().lower()
    # also accept forms like "feature review: yes" anywhere
    m2 = re.search(r"(?mi)feature\s+review[^:\n]*:\s*(yes|no)", text)
    if m2:
        return m2.group(1).strip().lower()
    return None

def normalize_yes_no(val):
    if isinstance(val, bool):
        return "yes" if val else "no"
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ["yes", "y", "true", "1", "on", "enabled"]:
            return "yes"
        if v in ["no", "n", "false", "0", "off", "disabled"]:
            return "no"
    return None

def get_migration_risk_fields(skill):
    # Determine migration risk boolean and attributes from top-level or nested dict
    risk = False
    from_v = None
    to_v = None
    changes = None
    mr = skill.get("migration_risk") if isinstance(skill, dict) else None
    if isinstance(mr, bool):
        risk = mr
    elif isinstance(mr, dict):
        risk = True
        from_v = mr.get("from_version") or mr.get("from") or mr.get("fromVersion")
        to_v = mr.get("to_version") or mr.get("to") or mr.get("toVersion")
        changes = mr.get("possible_changes") or mr.get("possibleChanges") or mr.get("changes")
    # Also consider top-level fields
    if isinstance(skill, dict):
        from_v = skill.get("from_version", from_v)
        to_v = skill.get("to_version", to_v)
        changes = skill.get("possible_changes", changes)
    return risk, from_v, to_v, changes

def has_all_control_file_refs_in_scheduler(text, base_rel="output/auto-update"):
    files = ["memory.md", "core.md", "skills.md", "migrations.md", "schedule.md", "backups.md", "run-log.md"]
    for f in files:
        if f"{base_rel}/{f}" not in text:
            return False
    return True

def scheduler_has_no_tools_commands(text):
    banned = [
        "openclaw", "cron", "launchd", "task scheduler", "crontab", "bash", "powershell",
        "cmd.exe", "systemctl", "service ", "at ", "schtasks", "windows", "macos", "linux",
        "python ", "python3 ", "node ", "npm ", "pip ", "sh ", "shell", "zsh"
    ]
    low = text.lower()
    return not any(b in low for b in banned)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    au_dir = os.path.join(output_dir, "auto-update")

    # Initialize checks
    checks = OrderedDict()
    # Load inputs
    prefs = read_json(os.path.join(input_dir, "preferences.json")) or {}
    installed = read_json(os.path.join(input_dir, "installed_skills.json"))
    if installed is None:
        installed = []
    tz = norm(read_text(os.path.join(input_dir, "timezone.txt")))

    # Expected values from preferences
    core_mode = (get_pref(prefs, "core_update_mode") or "").strip().lower()
    new_skill_default = (get_pref(prefs, "new_skill_default") or "").strip().lower()
    summary_style = (get_pref(prefs, "summary_style") or "").strip().lower()
    discovery_cadence = norm(get_pref(prefs, "discovery_cadence") or get_pref(prefs, "discovery cadence") or "")
    apply_cadence = norm(get_pref(prefs, "apply_cadence") or get_pref(prefs, "apply cadence") or "")
    quiet_hours = norm(get_pref(prefs, "quiet_hours") or get_pref(prefs, "quiet hours") or "")
    feature_review = normalize_yes_no(get_pref(prefs, "feature_review") or get_pref(prefs, "post_update_feature_review"))

    # Output files
    memory_path = os.path.join(au_dir, "memory.md")
    core_path = os.path.join(au_dir, "core.md")
    skills_path = os.path.join(au_dir, "skills.md")
    migrations_path = os.path.join(au_dir, "migrations.md")
    schedule_path = os.path.join(au_dir, "schedule.md")
    backups_path = os.path.join(au_dir, "backups.md")
    run_log_path = os.path.join(au_dir, "run-log.md")
    sched_instr_path = os.path.join(au_dir, "scheduler_instructions.txt")

    # 1) Required files exist
    required_exist = all(os.path.isfile(p) for p in [
        memory_path, core_path, skills_path, migrations_path, schedule_path,
        backups_path, run_log_path, sched_instr_path
    ])
    checks["required_files_exist"] = required_exist

    # Load outputs
    memory_txt = read_text(memory_path) if required_exist else ""
    core_txt = read_text(core_path) if required_exist else ""
    skills_txt = read_text(skills_path) if required_exist else ""
    migrations_txt = read_text(migrations_path) if required_exist else ""
    schedule_txt = read_text(schedule_path) if required_exist else ""
    backups_txt = read_text(backups_path) if required_exist else ""
    run_log_txt = read_text(run_log_path) if required_exist else ""
    sched_instr_txt = read_text(sched_instr_path) if required_exist else ""

    # 2) schedule.md fields
    sched_tz_ok = False
    sched_disc_ok = False
    sched_apply_ok = False
    sched_quiet_line = False
    sched_owner_ok = False

    if required_exist:
        # exact "Timezone: <TZ>"
        if tz:
            sched_tz_ok = f"Timezone: {tz}" in schedule_txt
        # discovery/apply cadence presence and match
        if discovery_cadence:
            sched_disc_ok = contains_ci(schedule_txt, f"Discovery cadence: {discovery_cadence}")
        if apply_cadence:
            sched_apply_ok = contains_ci(schedule_txt, f"Apply cadence: {apply_cadence}")
        # Quiet hours line must be present (value may be empty)
        sched_quiet_line = any(re.match(r"(?i)^\s*Quiet\s+hours\s*:", line) for line in schedule_txt.splitlines())
        # Ownership section including phrase that scheduler edits require approval and a No-op behavior line
        has_ownership_hdr = contains_ci(schedule_txt, "ownership")
        has_require_approval_phrase = contains_ci(schedule_txt, "scheduler edits") and contains_ci(schedule_txt, "require approval")
        has_noop_line = any(re.match(r"(?i)^\s*No-?op\s+behavior\s*:", line) for line in schedule_txt.splitlines())
        sched_owner_ok = has_ownership_hdr and has_require_approval_phrase and has_noop_line

    checks["schedule_timezone_match"] = sched_tz_ok
    checks["schedule_cadences_match"] = (sched_disc_ok and sched_apply_ok)
    checks["schedule_quiet_hours_line"] = sched_quiet_line
    checks["schedule_ownership_and_noop"] = sched_owner_ok

    # 3) core.md contents: mode, backup scope, feature review yes/no
    core_mode_ok = False
    core_backup_scope_ok = False
    core_feature_review_ok = False
    if required_exist:
        mode_in_file = parse_mode_from_core(core_txt)
        if core_mode and mode_in_file == core_mode:
            core_mode_ok = True
        core_backup_scope_ok = has_backup_scope_in_core(core_txt)
        fr_in_file = feature_review_value_in_core(core_txt)
        if feature_review in ("yes", "no") and fr_in_file == feature_review:
            core_feature_review_ok = True
    checks["core_mode_match"] = core_mode_ok
    checks["core_backup_scope_present"] = core_backup_scope_ok
    checks["core_feature_review_match"] = core_feature_review_ok

    # 4) memory.md: Status ongoing; Defaults with New skill default and Summary style
    mem_status_ok = False
    mem_new_skill_ok = False
    mem_summary_style_ok = False
    if required_exist:
        mem_status_ok = contains_ci(memory_txt, "status: ongoing")
        if new_skill_default:
            mem_new_skill_ok = contains_ci(memory_txt, f"New skill default: {new_skill_default}")
        if summary_style:
            mem_summary_style_ok = contains_ci(memory_txt, f"Summary style: {summary_style}")
    checks["memory_status_ongoing"] = mem_status_ok
    checks["memory_new_skill_default_match"] = mem_new_skill_ok
    checks["memory_summary_style_match"] = mem_summary_style_ok

    # 5) skills.md: Defaults and tracked skills with fields
    skills_defaults_ok = False
    skills_tracked_ok = False
    if required_exist:
        # Defaults section
        if new_skill_default:
            skills_defaults_ok = contains_ci(skills_txt, f"New skills inherit: {new_skill_default}")
        # Parse migrations pending slugs from migrations.md
        pending_section = extract_section(migrations_txt, "Pending")
        pending_slugs = set()
        for skill in installed if isinstance(installed, list) else []:
            risk, _, _, _ = get_migration_risk_fields(skill)
            if risk:
                pending_slugs.add(skill.get("slug", ""))
        # Parse skills ledger
        skills_map = parse_skills_md(skills_txt)
        per_slug_ok = True
        for skill in installed if isinstance(installed, list) else []:
            slug = skill.get("slug", "")
            location = skill.get("location", "")
            version = skill.get("installed_version", "")
            auto = skill.get("auto_update", None)
            # normalize auto_update expected value
            if isinstance(auto, bool):
                auto_expected = "yes" if auto else "no"
            elif isinstance(auto, str) and auto.strip():
                auto_expected = auto.strip().lower()
            else:
                auto_expected = "inherit"
            # Check presence
            entry = skills_map.get(slug)
            if not slug or not entry:
                per_slug_ok = False
                break
            # Compare fields (case-insensitive for values)
            loc_ok = contains_ci(f"location: {entry.get('location','')}", f"location: {location}")
            ver_ok = contains_ci(f"installed_version: {entry.get('installed_version','')}", f"installed_version: {version}")
            auto_val = (entry.get("auto_update", "") or "").strip().lower()
            auto_ok = (auto_val == auto_expected)
            lb_present = "last_backup" in entry  # value can be empty
            # migration_state rules: must be "clean" unless in pending list
            mig_state_val = (entry.get("migration_state", "") or "").strip().lower()
            if slug in pending_slugs:
                mig_ok = "migration_state" in entry  # any value acceptable when pending exists
            else:
                mig_ok = (mig_state_val == "clean")
            if not (loc_ok and ver_ok and auto_ok and lb_present and mig_ok):
                per_slug_ok = False
                break
        skills_tracked_ok = per_slug_ok
    checks["skills_defaults_match"] = skills_defaults_ok
    checks["skills_tracked_entries_valid"] = skills_tracked_ok

    # 6) migrations.md pending entries
    migrations_pending_ok = False
    migrations_cleared_header_ok = False
    if required_exist:
        pend_ok = True
        for skill in installed if isinstance(installed, list) else []:
            slug = skill.get("slug", "")
            risk, from_v, to_v, changes = get_migration_risk_fields(skill)
            if risk:
                # Ensure slug present under Pending section
                if slug and slug not in pending_section:
                    pend_ok = False
                    break
                # If from_version provided, ensure it appears in file
                if from_v and (str(from_v) not in pending_section):
                    pend_ok = False
                    break
                # If to_version provided, ensure it appears in file
                if to_v and (str(to_v) not in pending_section):
                    pend_ok = False
                    break
                # possible_changes one-line presence (just ensure text appears)
                if changes and (str(changes) not in pending_section):
                    pend_ok = False
                    break
        migrations_pending_ok = pend_ok
        migrations_cleared_header_ok = bool(re.search(r"(?mi)^##\s*Cleared\s*$", migrations_txt))
    checks["migrations_pending_entries_valid"] = migrations_pending_ok
    checks["migrations_cleared_section_present"] = migrations_cleared_header_ok

    # 7) scheduler_instructions.txt message content and constraints
    sched_refs_ok = False
    sched_steps_ok = False
    sched_no_tools = False
    if required_exist:
        sched_refs_ok = has_all_control_file_refs_in_scheduler(sched_instr_txt, base_rel="output/auto-update")
        # Verify it mentions key steps
        steps = [
            ("read", ["memory.md", "core.md", "skills.md", "migrations.md", "schedule.md"]),
            ("inspect", ["updates", "available"]),
            ("backup", ["backup", "back up"]),
            ("skip", ["skip", "blocked", "migration", "pending"]),
            ("apply", ["apply", "only"]),
            ("verify", ["verify", "health"]),
            ("write", ["write", "backups.md", "run-log.md"]),
        ]
        text_low = sched_instr_txt.lower()
        steps_pass = True
        # read check: ensure "read" plus references already enforced separately; here we just require the word "read"
        if "read" not in text_low:
            steps_pass = False
        # inspect updates
        if not ("inspect" in text_low and "update" in text_low):
            steps_pass = False
        # backup mention
        if not ("backup" in text_low or "back up" in text_low):
            steps_pass = False
        # skip blocked and migration pending
        if not ("skip" in text_low and "migration" in text_low and "pending" in text_low):
            steps_pass = False
        # apply only permitted
        if not ("apply" in text_low and "only" in text_low):
            steps_pass = False
        # verify health
        if not ("verify" in text_low and "health" in text_low):
            steps_pass = False
        # write backups.md and run-log.md
        if not ("write" in text_low and "backups.md" in text_low and "run-log.md" in text_low):
            steps_pass = False
        sched_steps_ok = steps_pass
        # No tools/commands
        sched_no_tools = scheduler_has_no_tools_commands(sched_instr_txt)
    checks["scheduler_refs_and_paths_ok"] = sched_refs_ok
    checks["scheduler_steps_message_ok"] = sched_steps_ok
    checks["scheduler_tool_agnostic"] = sched_no_tools

    # 8) backups.md and run-log.md structure
    backups_structure_ok = False
    runlog_template_ok = False
    if required_exist:
        # backups.md must have top-level heading and Core and Skills subsections with fields
        has_heading = bool(re.search(r"(?m)^#\s+.*", backups_txt))
        has_core = contains_ci(backups_txt, "core")
        has_skills = contains_ci(backups_txt, "skills")
        # fields date/version/path anywhere
        has_date = contains_ci(backups_txt, "date:")
        has_version = contains_ci(backups_txt, "version:")
        has_path = contains_ci(backups_txt, "path:")
        backups_structure_ok = has_heading and has_core and has_skills and has_date and has_version and has_path

        # run-log.md must contain template fields
        fields = ["Trigger:", "Core:", "Skills:", "Backups:", "Migrations:", "Verification:", "Next action:"]
        runlog_template_ok = all(any(line.strip().lower().startswith(f.lower()) for line in run_log_txt.splitlines()) for f in fields)
    checks["backups_structure_ok"] = backups_structure_ok
    checks["runlog_template_ok"] = runlog_template_ok

    # Aggregate reward across 8 deterministic groups:
    group_checks = [
        checks["required_files_exist"],
        (checks["schedule_timezone_match"] and checks["schedule_cadences_match"] and checks["schedule_quiet_hours_line"] and checks["schedule_ownership_and_noop"]),
        (checks["core_mode_match"] and checks["core_backup_scope_present"] and checks["core_feature_review_match"]),
        (checks["memory_status_ongoing"] and checks["memory_new_skill_default_match"] and checks["memory_summary_style_match"]),
        (checks["skills_defaults_match"] and checks["skills_tracked_entries_valid"]),
        (checks["migrations_pending_entries_valid"] and checks["migrations_cleared_section_present"]),
        (checks["scheduler_refs_and_paths_ok"] and checks["scheduler_steps_message_ok"] and checks["scheduler_tool_agnostic"]),
        (checks["backups_structure_ok"] and checks["runlog_template_ok"]),
    ]
    passed = sum(1 for g in group_checks if g)
    reward = passed / 8.0 if required_exist else 0.0

    # Ensure no-op baseline 0.0 when output missing or empty
    if not os.path.isdir(au_dir):
        reward = 0.0

    out = OrderedDict()
    out["reward"] = reward
    for k, v in checks.items():
        out[k] = bool(v)
    print(json.dumps(out))

if __name__ == "__main__":
    main()