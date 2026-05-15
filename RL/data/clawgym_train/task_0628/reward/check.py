import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def file_exists(path):
    try:
        return os.path.isfile(path)
    except Exception:
        return False

def list_dir(path):
    try:
        return os.listdir(path)
    except Exception:
        return []

def count_typed_entries(md_text):
    # Matches lines like: [TYPE] YYYY-MM-DD: content
    pattern = re.compile(r'^\[(DECISION|PREFERENCE|FACT|ENTITY|EPISODE|LESSON|AGENT_IDENTITY)\] \d{4}-\d{2}-\d{2}: .+', re.MULTILINE)
    return len(re.findall(pattern, md_text))

def has_specific_typed(md_text, type_name):
    pattern = re.compile(r'^\[' + re.escape(type_name) + r'\] \d{4}-\d{2}-\d{2}: .+', re.MULTILINE)
    return bool(re.search(pattern, md_text))

def find_topic_file(memory_dir, exclude_names):
    # Find any file matching kebab-case topic file: [a-z0-9-]+.md, not in exclude_names
    try:
        for name in list_dir(memory_dir):
            if name in exclude_names:
                continue
            if re.fullmatch(r'[a-z0-9-]+\.md', name):
                return os.path.join(memory_dir, name)
    except Exception:
        pass
    return None

def topic_has_yaml_frontmatter(text):
    # Must start with '---' on the first line, include 'summary:' list and 'updated: YYYY-MM-DD' before closing '---'
    if not text.startswith("---"):
        return False
    # Find the closing '---' after the first line
    m = re.search(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL | re.MULTILINE)
    if not m:
        return False
    yaml_block = m.group(1)
    has_summary = re.search(r'\n?\s*summary:\s*\n\s*-\s*.+', "\n" + yaml_block) is not None
    has_updated = re.search(r'\n\s*updated:\s*\d{4}-\d{2}-\d{2}\s*(\n|$)', yaml_block) is not None
    return has_summary and has_updated

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    memory_dir = os.path.join(output_dir, "memory")
    agents_path = os.path.join(output_dir, "AGENTS.md")
    identity_path = os.path.join(output_dir, "IDENTITY.md")
    memory_path = os.path.join(output_dir, "MEMORY.md")
    soul_path = os.path.join(output_dir, "SOUL.md")
    user_path = os.path.join(output_dir, "USER.md")
    tools_path = os.path.join(output_dir, "TOOLS.md")
    heartbeat_path = os.path.join(output_dir, "HEARTBEAT.md")
    decisions_path = os.path.join(memory_dir, "decisions.md")
    session_date_file = os.path.join(input_dir, "session_date.txt")

    checks = {
        "exists_soul": False,
        "exists_identity": False,
        "exists_user": False,
        "exists_agents": False,
        "exists_memory": False,
        "exists_tools": False,
        "exists_heartbeat": False,
        "exists_decisions_md": False,
        "exists_daily_note": False,

        "identity_has_fields": False,

        "agents_has_session_start_section": False,
        "agents_has_read_order_refs": False,
        "agents_has_wal_protocol": False,
        "agents_has_always_search_rule": False,
        "agents_has_security_boundary": False,

        "memory_has_three_typed_entries": False,
        "memory_has_decision_entry": False,
        "memory_has_preference_entry": False,
        "memory_has_reversal_decision": False,

        "decisions_has_typed_entry": False,

        "has_topic_file": False,
        "topic_has_yaml_frontmatter": False,

        "user_has_timezone_line": False,
        "user_has_comm_prefs_section": False,

        "soul_has_boundaries_section": False,
        "soul_mentions_sacred_or_never_share": False,
    }

    # Existence checks
    checks["exists_soul"] = file_exists(soul_path)
    checks["exists_identity"] = file_exists(identity_path)
    checks["exists_user"] = file_exists(user_path)
    checks["exists_agents"] = file_exists(agents_path)
    checks["exists_memory"] = file_exists(memory_path)
    checks["exists_tools"] = file_exists(tools_path)
    checks["exists_heartbeat"] = file_exists(heartbeat_path)
    checks["exists_decisions_md"] = file_exists(decisions_path)

    # Compute daily note filename from session_date.txt
    session_date = None
    if file_exists(session_date_file):
        raw_date = read_text(session_date_file).strip()
        # Accept ISO date yyyy-mm-dd possibly with time; only take date part up to 10 chars if matches
        m = re.match(r'^\s*(\d{4}-\d{2}-\d{2})', raw_date)
        if m:
            session_date = m.group(1)
    if session_date:
        daily_file = os.path.join(memory_dir, f"{session_date}.md")
        checks["exists_daily_note"] = file_exists(daily_file)
    else:
        # No positive credit if no session date provided
        checks["exists_daily_note"] = False
        daily_file = None

    # IDENTITY.md content checks
    if checks["exists_identity"]:
        ident_txt = read_text(identity_path)
        name_ok = re.search(r'(?im)^\s*[-*]?\s*\**Name\**:\s*.+', ident_txt) or re.search(r'(?i)Name:\s*.+', ident_txt)
        creature_ok = re.search(r'(?im)^\s*[-*]?\s*\**Creature\**:\s*.+', ident_txt) or re.search(r'(?i)Creature:\s*.+', ident_txt)
        vibe_ok = re.search(r'(?im)^\s*[-*]?\s*\**Vibe\**:\s*.+', ident_txt) or re.search(r'(?i)Vibe:\s*.+', ident_txt)
        emoji_ok = re.search(r'(?im)^\s*[-*]?\s*\**Emoji\**:\s*.+', ident_txt) or re.search(r'(?i)Emoji:\s*.+', ident_txt)
        checks["identity_has_fields"] = bool(name_ok and creature_ok and vibe_ok and emoji_ok)

    # AGENTS.md content checks
    if checks["exists_agents"]:
        agents_txt = read_text(agents_path)
        # Session Start section
        checks["agents_has_session_start_section"] = ("Session Start" in agents_txt)
        # Read order references
        has_soul_ref = "SOUL.md" in agents_txt
        has_user_ref = "USER.md" in agents_txt
        has_memory_md_ref = "MEMORY.md" in agents_txt
        has_daily_ref = bool(re.search(r'memory/\d{4}-\d{2}-\d{2}\.md', agents_txt)) or re.search(r'(?i)daily', agents_txt) is not None
        checks["agents_has_read_order_refs"] = bool(has_soul_ref and has_user_ref and has_memory_md_ref and has_daily_ref)
        # WAL protocol exact string
        checks["agents_has_wal_protocol"] = ("STOP → WRITE → THEN RESPOND" in agents_txt)
        # Always-Search protocol exact phrase
        checks["agents_has_always_search_rule"] = ("Always run memory_search before answering about prior context" in agents_txt)
        # Security boundary statement: mention MEMORY.md and SOUL.md and not sharing externally
        has_names = ("MEMORY.md" in agents_txt and "SOUL.md" in agents_txt)
        has_never_share = re.search(r'(?i)never\s+share', agents_txt) is not None
        has_external = re.search(r'(?i)extern', agents_txt) is not None
        checks["agents_has_security_boundary"] = bool(has_names and has_never_share and has_external)

    # MEMORY.md content checks
    if checks["exists_memory"]:
        mem_txt = read_text(memory_path)
        checks["memory_has_three_typed_entries"] = (count_typed_entries(mem_txt) >= 3)
        checks["memory_has_decision_entry"] = has_specific_typed(mem_txt, "DECISION")
        checks["memory_has_preference_entry"] = has_specific_typed(mem_txt, "PREFERENCE")
        checks["memory_has_reversal_decision"] = re.search(r'^\[DECISION\].*\(reverses\s+\d{4}-\d{2}-\d{2}\s+decision\)', mem_txt, re.IGNORECASE | re.MULTILINE) is not None

    # decisions.md typed entry
    if checks["exists_decisions_md"]:
        dec_txt = read_text(decisions_path)
        checks["decisions_has_typed_entry"] = (count_typed_entries(dec_txt) >= 1)

    # Topic file presence and YAML L1 frontmatter
    topic_file = None
    exclude = set(["decisions.md"])
    if daily_file:
        exclude.add(os.path.basename(daily_file))
    if os.path.isdir(memory_dir):
        tf = find_topic_file(memory_dir, exclude)
        if tf:
            checks["has_topic_file"] = True
            topic_file = tf
            topic_text = read_text(topic_file)
            checks["topic_has_yaml_frontmatter"] = topic_has_yaml_frontmatter(topic_text)
        else:
            checks["has_topic_file"] = False
            checks["topic_has_yaml_frontmatter"] = False

    # USER.md checks
    if checks["exists_user"]:
        user_txt = read_text(user_path)
        checks["user_has_timezone_line"] = re.search(r'(?im)^\s*[-*]?\s*\**Timezone\**:\s*.+', user_txt) is not None or ("Timezone:" in user_txt)
        checks["user_has_comm_prefs_section"] = re.search(r'(?i)Communication Preferences', user_txt) is not None

    # SOUL.md checks
    if checks["exists_soul"]:
        soul_txt = read_text(soul_path)
        checks["soul_has_boundaries_section"] = re.search(r'(?i)Boundaries', soul_txt) is not None
        has_sacred = re.search(r'(?i)sacred', soul_txt) is not None
        has_never_share_external = (re.search(r'(?i)never\s+share', soul_txt) is not None) and (re.search(r'(?i)extern', soul_txt) is not None)
        checks["soul_mentions_sacred_or_never_share"] = bool(has_sacred or has_never_share_external)

    # Compute reward as proportion of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Ensure strict 0.0 for no-op (no outputs at all)
    # If output dir missing or empty critical files missing, passed likely 0. But enforce explicitly:
    if not os.path.isdir(output_dir):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()