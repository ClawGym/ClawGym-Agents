import json
import os
import re
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return content, content.splitlines()
    except Exception:
        return None, []

def parse_latest_date_and_session_ids(logs_path):
    latest_date = None
    session_ids = set()
    date_pattern = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
    s_id_pattern = re.compile(r"\bS-\d+\b")

    def extract_date_from_value(val):
        if isinstance(val, str):
            m = date_pattern.search(val)
            if m:
                return m.group(1)
        return None

    if not os.path.isfile(logs_path):
        return None, set()

    try:
        with open(logs_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    # ignore malformed lines
                    continue

                # Try common timestamp keys first
                for k in ["timestamp", "time", "date", "datetime", "created_at", "updated_at"]:
                    if k in obj:
                        d = extract_date_from_value(obj[k])
                        if d:
                            latest_date = d if (latest_date is None or d > latest_date) else latest_date

                # Fallback: scan any string field for a date
                if latest_date is None:
                    for v in obj.values():
                        d = extract_date_from_value(v)
                        if d:
                            latest_date = d if (latest_date is None or d > latest_date) else latest_date

                # Collect session identifiers
                # Prefer explicit fields
                for k in ["session_id", "sessionId", "id"]:
                    if k in obj and isinstance(obj[k], str):
                        # If it matches S-###, use it; else include as is
                        m = s_id_pattern.search(obj[k])
                        if m:
                            session_ids.add(m.group(0))
                        else:
                            session_ids.add(obj[k])

                # Also scan all string values for S-### patterns
                for v in obj.values():
                    if isinstance(v, str):
                        for m in s_id_pattern.findall(v):
                            session_ids.add(m)
    except Exception:
        # On unexpected errors, return what we have
        pass

    return latest_date, session_ids

def count_bullets_under_section_memory(lines, section_label, other_labels):
    # Find the first line that mentions the section label (case-insensitive)
    idx = -1
    target_lower = section_label.lower()
    for i, line in enumerate(lines):
        if target_lower in line.strip().lower():
            idx = i
            break
    if idx == -1:
        return 0
    bullets = 0
    other_lowers = [lbl.lower() for lbl in other_labels]
    for j in range(idx + 1, len(lines)):
        s = lines[j].strip()
        # Stop if another section header is encountered
        if s.startswith("#") or any(lbl in s.lower() for lbl in other_lowers):
            break
        if lines[j].lstrip().startswith("- "):
            bullets += 1
    return bullets

def count_bullets_under_exact_h2(lines, section_title):
    # Look for exact "## {section_title}" header (strip trailing spaces)
    idx = -1
    target = f"## {section_title}"
    for i, line in enumerate(lines):
        if line.strip() == target:
            idx = i
            break
    if idx == -1:
        return 0
    bullets = 0
    for j in range(idx + 1, len(lines)):
        s = lines[j].strip()
        # Stop at next H2
        if s.startswith("## "):
            break
        if lines[j].lstrip().startswith("- "):
            bullets += 1
    return bullets

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False)
    checks = {
        # Parsing input (not scored)
        "parsed_latest_date": False,

        # MEMORY.md checks
        "has_memory_md": False,
        "memory_has_review_summary_with_date_and_count": False,
        "memory_patterns_section_has_bullet": False,
        "memory_gotchas_section_has_bullet": False,
        "memory_user_prefs_section_has_bullet": False,

        # Daily file checks
        "has_daily_md": False,
        "daily_filename_matches_latest_date": False,
        "daily_sections_have_bullets": False,
        "daily_includes_session_id": False,

        # AGENTS.md checks
        "has_agents_md": False,
        "agents_has_workflow_changes_section": False,
        "agents_mentions_snapshot_hourly_or_compound_prefix": False,

        # Commit message checks
        "has_commit_message": False,
        "commit_message_starts_with_prefix": False,
        "commit_message_has_more_text": False,
    }

    # Determine latest date and session IDs from input logs
    logs_path = os.path.join(input_dir, "session_logs.jsonl")
    latest_date, session_ids = parse_latest_date_and_session_ids(logs_path)
    if latest_date:
        checks["parsed_latest_date"] = True

    # Paths
    memory_md_path = os.path.join(output_dir, "MEMORY.md")
    daily_md_path = os.path.join(output_dir, "memory", f"{latest_date}.md") if latest_date else None
    agents_md_path = os.path.join(output_dir, "AGENTS.md")
    commit_msg_path = os.path.join(output_dir, "commit_message.txt")

    # MEMORY.md validations
    mem_content, mem_lines = read_text_file(memory_md_path)
    if mem_content is not None:
        checks["has_memory_md"] = True
        # Review Summary line with date and a sessions count (any integer)
        if latest_date:
            found_summary = False
            for line in mem_lines:
                if "Review Summary" in line:
                    # Date present?
                    if latest_date in line and re.search(r"\d+", line):
                        found_summary = True
                        break
            if found_summary:
                checks["memory_has_review_summary_with_date_and_count"] = True

        # Sections with at least one bullet "- "
        labels = ["Patterns That Work", "Gotchas to Avoid", "User Preferences"]
        # Count bullets under each section
        for label in labels:
            bullets = count_bullets_under_section_memory(
                mem_lines, label, [l for l in labels if l != label]
            )
            if label == "Patterns That Work" and bullets >= 1:
                checks["memory_patterns_section_has_bullet"] = True
            if label == "Gotchas to Avoid" and bullets >= 1:
                checks["memory_gotchas_section_has_bullet"] = True
            if label == "User Preferences" and bullets >= 1:
                checks["memory_user_prefs_section_has_bullet"] = True

    # Daily memory validations
    daily_content = None
    daily_lines = []
    if latest_date and daily_md_path and os.path.isfile(daily_md_path):
        checks["has_daily_md"] = True
        daily_content, daily_lines = read_text_file(daily_md_path)
        # Filename matches latest date
        checks["daily_filename_matches_latest_date"] = True

        # Section headers "## Sessions", "## Decisions", "## Learnings", "## Open Items" each with at least one "- "
        required_sections = ["Sessions", "Decisions", "Learnings", "Open Items"]
        section_bullets_ok = True
        for sec in required_sections:
            bullets = count_bullets_under_exact_h2(daily_lines, sec)
            if bullets < 1:
                section_bullets_ok = False
                break
        if section_bullets_ok:
            checks["daily_sections_have_bullets"] = True

        # Include at least one session identifier from logs
        included = False
        if session_ids and daily_content:
            lower_content = daily_content  # keep original case for exact substring search
            for sid in session_ids:
                if isinstance(sid, str) and sid and sid in lower_content:
                    included = True
                    break
        if included:
            checks["daily_includes_session_id"] = True

    # AGENTS.md validations
    agents_content, agents_lines = read_text_file(agents_md_path)
    if agents_content is not None:
        checks["has_agents_md"] = True
        # Contains "Workflow Changes" section
        if re.search(r"\bWorkflow Changes\b", agents_content, flags=re.IGNORECASE):
            checks["agents_has_workflow_changes_section"] = True
        # Mentions 'snapshot' or 'hourly' or exact commit pattern 'compound: daily review'
        lc_agents = agents_content.lower()
        if ("snapshot" in lc_agents) or ("hourly" in lc_agents) or ("compound: daily review" in lc_agents):
            checks["agents_mentions_snapshot_hourly_or_compound_prefix"] = True

    # Commit message validations
    commit_content, commit_lines = read_text_file(commit_msg_path)
    if commit_content is not None and commit_lines:
        checks["has_commit_message"] = True
        if latest_date:
            prefix = f"compound: daily review {latest_date}"
            first_line = commit_lines[0].rstrip("\n")
            if first_line.startswith(prefix):
                checks["commit_message_starts_with_prefix"] = True
                # Additional character on same line or a second line exists
                more_text_same_line = len(first_line) > len(prefix)
                second_line_exists = len(commit_lines) > 1
                if more_text_same_line or second_line_exists:
                    checks["commit_message_has_more_text"] = True

    # Compute reward: only artifact-dependent checks contribute
    scored_keys = [
        "has_memory_md",
        "memory_has_review_summary_with_date_and_count",
        "memory_patterns_section_has_bullet",
        "memory_gotchas_section_has_bullet",
        "memory_user_prefs_section_has_bullet",
        "has_daily_md",
        "daily_filename_matches_latest_date",
        "daily_sections_have_bullets",
        "daily_includes_session_id",
        "has_agents_md",
        "agents_has_workflow_changes_section",
        "agents_mentions_snapshot_hourly_or_compound_prefix",
        "has_commit_message",
        "commit_message_starts_with_prefix",
        "commit_message_has_more_text",
    ]
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    total = len(scored_keys)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure reward is exactly 0.0 if no outputs or missing required artifacts (no-op baseline)
    # If none of the output-dependent checks passed, reward should be 0.0 already.
    if passed == 0:
        reward = 0.0

    # Print result JSON (reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()