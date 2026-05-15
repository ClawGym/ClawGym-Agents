import json
import os
import sys
import csv
import re

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
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    items.append(json.loads(s))
                except Exception:
                    return None
        return items
    except Exception:
        return None

def read_csv_dicts(path):
    rows = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                # normalize keys and strip values
                norm = {}
                for k, v in r.items():
                    key = k.strip() if isinstance(k, str) else k
                    val = v.strip() if isinstance(v, str) else ("" if v is None else v)
                    norm[key] = val
                rows.append(norm)
        return rows
    except Exception:
        return None

def parse_backup_scope_yaml(path):
    # Minimal YAML parser for the expected structure:
    # always_snapshot:
    #   - item1
    #   - item2
    # optional_snapshot:
    #   - item3
    # Returns dict with lists; if missing list, treat as empty.
    result = {"always_snapshot": [], "optional_snapshot": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None
    current_key = None
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith(":"):
            key = stripped[:-1].strip()
            if key in ("always_snapshot", "optional_snapshot"):
                current_key = key
            else:
                current_key = None
            continue
        if current_key and stripped.startswith("- "):
            item = stripped[2:]
            result[current_key].append(item)
        elif current_key and re.match(r"^[\-\s]+\-\s+.+$", line):
            # Handle indented list items like "  - item"
            m = re.search(r"-\s+(.+)$", line)
            if m:
                result[current_key].append(m.group(1))
    return result

def lines_list(text):
    return text.splitlines() if text is not None else []

def contains_exact_line(text, target):
    if text is None:
        return False
    for ln in text.splitlines():
        if ln.strip() == target.strip():
            return True
    return False

def count_exact_line(text, target):
    if text is None:
        return 0
    cnt = 0
    t = target.strip()
    for ln in text.splitlines():
        if ln.strip() == t:
            cnt += 1
    return cnt

def find_line_indices(text, predicate):
    idxs = []
    if text is None:
        return idxs
    for i, ln in enumerate(text.splitlines()):
        if predicate(ln):
            idxs.append(i)
    return idxs

def next_section_or_block_end(lines, start_idx, block_starts_predicates):
    # Scan forward until we hit a new block start or section header
    end = len(lines)
    for j in range(start_idx + 1, len(lines)):
        l = lines[j].strip()
        if l.startswith("## "):
            return j
        for pred in block_starts_predicates:
            try:
                if pred(lines[j]):
                    return j
            except Exception:
                pass
    return end

def check_memory(memory_text, prefs):
    # Must contain "## Defaults" and lines:
    # New skill default: <prefs.new_skill_default>
    # OpenClaw mode: <prefs.openclaw_mode>
    # Summary style: <prefs.summary_style>
    if memory_text is None:
        return False
    has_header = any(ln.strip() == "## Defaults" for ln in memory_text.splitlines())
    ls1 = contains_exact_line(memory_text, f"New skill default: {prefs.get('new_skill_default','')}")
    ls2 = contains_exact_line(memory_text, f"OpenClaw mode: {prefs.get('openclaw_mode','')}")
    ls3 = contains_exact_line(memory_text, f"Summary style: {prefs.get('summary_style','')}")
    return has_header and ls1 and ls2 and ls3

def check_openclaw(openclaw_text, prefs, backup_scope):
    if openclaw_text is None:
        return False
    # Auto-update mode line
    if not contains_exact_line(openclaw_text, f"Auto-update mode: {prefs.get('openclaw_mode','')}"):
        return False
    # Dry-run before apply
    dry = "yes" if prefs.get("apply_mode") == "notify-first" else "no"
    if not contains_exact_line(openclaw_text, f"Dry-run before apply: {dry}"):
        return False
    # Backup scope bullets
    # Ensure the section markers exist
    if not any(ln.strip() == "Always snapshot:" for ln in openclaw_text.splitlines()):
        # Accept also with a hyphen prefix "- Always snapshot:"
        if not any(ln.strip() == "- Always snapshot:" for ln in openclaw_text.splitlines()):
            return False
    if not any(ln.strip() == "Optional snapshot:" for ln in openclaw_text.splitlines()):
        if not any(ln.strip() == "- Optional snapshot:" for ln in openclaw_text.splitlines()):
            return False
    # For each item, ensure exactly one bullet line exists
    def count_bullet(item):
        pattern = re.compile(r"^\s*-\s+" + re.escape(item) + r"\s*$")
        cnt = 0
        for ln in openclaw_text.splitlines():
            if pattern.match(ln):
                cnt += 1
        return cnt
    always_items = backup_scope.get("always_snapshot", []) if backup_scope else []
    optional_items = backup_scope.get("optional_snapshot", []) if backup_scope else []
    for it in always_items:
        if count_bullet(it) != 1:
            return False
    for it in optional_items:
        if count_bullet(it) != 1:
            return False
    return True

def check_skills(skills_text, prefs, skills_rows):
    if skills_text is None:
        return False
    lines = skills_text.splitlines()
    # Defaults header and line
    if not any(ln.strip() == "## Defaults" for ln in lines):
        return False
    if not contains_exact_line(skills_text, f"New skills inherit: {prefs.get('new_skill_default','')}"):
        return False
    # Tracked Skills blocks
    if not any(ln.strip() == "## Tracked Skills" for ln in lines):
        return False
    # Extract order of "- slug:" occurrences
    slug_order = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        m = re.match(r"^- slug:\s*(.*)$", s)
        if m:
            slug_order.append((m.group(1), i))
    # Verify all CSV slugs present
    expected_slugs = sorted([r.get("slug","") for r in skills_rows], key=lambda x: x.lower())
    present_slugs = [s for s,_ in slug_order]
    # Must contain each expected slug exactly once
    if sorted(present_slugs, key=lambda x: x.lower()) != sorted(expected_slugs, key=lambda x: x.lower()):
        return False
    # Enforce alphabetical order by slug in file
    if [s.lower() for s,_ in slug_order] != [s.lower() for s in expected_slugs]:
        return False
    # For each slug, check the block fields
    index_by_slug = {s:i for s,i in slug_order}
    # Define block end predicate as new "- slug:" or new section header
    def is_new_slug(line):
        return line.strip().startswith("- slug:")
    ok_all = True
    for slug in expected_slugs:
        start_i = index_by_slug.get(slug, None)
        if start_i is None:
            ok_all = False
            break
        end_i = next_section_or_block_end(lines, start_i, [is_new_slug])
        block = [ln.strip().rstrip() for ln in lines[start_i+1:end_i]]
        # Prepare expected field lines; values may be empty
        row = next((r for r in skills_rows if r.get("slug","") == slug), {})
        exp = [
            f"- location: {row.get('location','')}",
            f"- installed_version: {row.get('installed_version','')}",
            f"- auto_update: {row.get('auto_update','')}",
            f"- last_backup: {row.get('last_backup','')}",
            f"- migration_state: {row.get('migration_state','')}",
        ]
        # Check that each expected line appears anywhere in this block
        for e in exp:
            if e not in block:
                ok_all = False
                break
        if not ok_all:
            break
    return ok_all

def check_schedule(schedule_text, prefs):
    if schedule_text is None:
        return False
    required = [
        f"Timezone: {prefs.get('timezone','')}",
        "Discovery cadence: daily",
        f"Apply cadence: {prefs.get('cron','')}",
        f"Quiet hours: {prefs.get('quiet_hours','')}",
        f"Scheduler type: {prefs.get('scheduler_type','')}",
        "Who may edit it: owner",
        f"No-op behavior: {'report-only' if prefs.get('apply_mode')=='notify-first' else 'apply-approved'}",
    ]
    for r in required:
        if not contains_exact_line(schedule_text, r):
            return False
    return True

def check_backups(backups_text, skills_rows):
    if backups_text is None:
        return False
    lines = backups_text.splitlines()
    if not any(ln.strip() == "## Skills" for ln in lines):
        return False
    # Collect slug block indices
    slug_indices = []
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*-\s+slug:\s*(.*)$", ln.strip())
        if m:
            slug_indices.append((m.group(1), i))
    expected_slugs = sorted([r.get("slug","") for r in skills_rows], key=lambda x: x.lower())
    present_slugs = [s for s,_ in slug_indices]
    # Must contain each expected slug exactly once
    if sorted(present_slugs, key=lambda x: x.lower()) != sorted(expected_slugs, key=lambda x: x.lower()):
        return False
    # Enforce alphabetical order
    if [s.lower() for s,_ in slug_indices] != [s.lower() for s in expected_slugs]:
        return False
    # Validate each block contains date/version/path
    def is_new_slug(line):
        return line.strip().startswith("- slug:")
    ok_all = True
    for slug, idx in slug_indices:
        end_i = next_section_or_block_end(lines, idx, [is_new_slug])
        block = [ln.strip() for ln in lines[idx+1:end_i]]
        # version from skills.csv
        row = next((r for r in skills_rows if r.get("slug","") == slug), {})
        exp_date = "date: TBD"
        exp_version = f"version: {row.get('installed_version','')}"
        exp_path = "path: TBD"
        # Each must appear (any order)
        if exp_date not in block or exp_version not in block or exp_path not in block:
            ok_all = False
            break
    return ok_all

def check_migrations(migrations_text, migrations_records):
    if migrations_text is None:
        return False
    lines = migrations_text.splitlines()
    # Require sections
    if not any(ln.strip() == "## Pending" for ln in lines):
        return False
    if not any(ln.strip() == "## Cleared" for ln in lines):
        return False
    # Build index of slug positions in Pending area
    # Find start of Pending and end at Cleared
    try:
        pending_start = next(i for i,ln in enumerate(lines) if ln.strip() == "## Pending")
    except StopIteration:
        return False
    try:
        cleared_start = next(i for i,ln in enumerate(lines) if ln.strip() == "## Cleared")
    except StopIteration:
        return False
    pending_lines = lines[pending_start+1:cleared_start]
    # Find blocks
    slug_positions = []
    for i, ln in enumerate(pending_lines):
        s = ln.strip()
        m = re.match(r"^- slug:\s*(.*)$", s)
        if m:
            slug_positions.append((m.group(1), i))
    # For each record, verify presence
    ok_all = True
    for rec in migrations_records:
        slug = str(rec.get("slug",""))
        from_v = str(rec.get("from_version",""))
        to_v = str(rec.get("to_version",""))
        changes = str(rec.get("possible_changes",""))
        decision = str(rec.get("user_decision",""))
        # Find the block for this slug
        matches = [pos for pos in slug_positions if pos[0] == slug]
        if not matches:
            ok_all = False
            break
        _, idx = matches[0]
        # Scan till next slug or end
        # Identify next slug index
        next_idx_candidates = [p for s2,p in slug_positions if p > idx]
        end_rel = min(next_idx_candidates) if next_idx_candidates else len(pending_lines)
        block = [ln.strip() for ln in pending_lines[idx+1:end_rel]]
        expects = [
            f"from_version: {from_v}",
            f"to_version: {to_v}",
            f"possible_changes: {changes}",
            f"user_decision: {decision}",
        ]
        for e in expects:
            if e not in block:
                ok_all = False
                break
        if not ok_all:
            break
    return ok_all

def check_runlog(runlog_text, prefs, skills_rows):
    if runlog_text is None:
        return False
    lines = [ln.strip() for ln in runlog_text.splitlines()]
    if "# Run Log" not in lines:
        return False
    if "## Setup" not in lines:
        return False
    # Compute allowed and paused lists
    def lc(s): return (s or "").strip().lower()
    new_skill_default = lc(prefs.get("new_skill_default",""))
    allowed_set = set()
    paused_set = set()
    for r in skills_rows:
        slug = r.get("slug","")
        au = lc(r.get("auto_update",""))
        mig = lc(r.get("migration_state",""))
        if au == "yes" or (au == "inherit" and new_skill_default == "all-in"):
            allowed_set.add(slug)
        if au == "no" or mig in ("pending", "ask-first"):
            paused_set.add(slug)
    allowed_list = sorted(list(allowed_set), key=lambda x: x.lower())
    paused_list = sorted(list(paused_set), key=lambda x: x.lower())
    allowed_str = ", ".join(allowed_list)
    paused_str = ", ".join(paused_list)
    # Required lines
    reqs = [
        f"Trigger: setup",
        f"OpenClaw mode: {prefs.get('openclaw_mode','')}",
        f"Allowed skills: {allowed_str}",
        f"Paused (by migration or policy): {paused_str}",
        f"Next action: schedule daily run at {prefs.get('cron','')} in {prefs.get('timezone','')} with mode {prefs.get('apply_mode','')}",
    ]
    for r in reqs:
        if r not in lines:
            return False
    return True

def check_jobmessage(job_text):
    if job_text is None:
        return False
    lines = [ln.strip() for ln in job_text.splitlines() if ln.strip() != ""]
    required_lines = [
        "read output/auto-update/memory.md",
        "read output/auto-update/openclaw.md",
        "read output/auto-update/skills.md",
        "read output/auto-update/migrations.md",
        "respect the modes and per-skill rules",
        "create backups for approved targets",
        "skip blocked items (no, pending, ask-first)",
        "apply allowed changes",
        "verify health",
        "write output/auto-update/backups.md and output/auto-update/run-log.md",
    ]
    # Each must appear exactly once
    for r in required_lines:
        if lines.count(r) != 1:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    auto_dir = os.path.join(output_dir, "auto-update")

    # Load inputs
    prefs = read_json(os.path.join(input_dir, "prefs.json")) or {}
    skills_rows = read_csv_dicts(os.path.join(input_dir, "skills.csv")) or []
    backup_scope = parse_backup_scope_yaml(os.path.join(input_dir, "backup_scope.yaml"))
    migrations_records = read_jsonl(os.path.join(input_dir, "migrations.jsonl")) or []

    # Load outputs
    memory_text = read_text(os.path.join(auto_dir, "memory.md"))
    openclaw_text = read_text(os.path.join(auto_dir, "openclaw.md"))
    skills_text = read_text(os.path.join(auto_dir, "skills.md"))
    schedule_text = read_text(os.path.join(auto_dir, "schedule.md"))
    backups_text = read_text(os.path.join(auto_dir, "backups.md"))
    migrations_text = read_text(os.path.join(auto_dir, "migrations.md"))
    runlog_text = read_text(os.path.join(auto_dir, "run-log.md"))
    job_text = read_text(os.path.join(auto_dir, "job-message.txt"))

    checks = {
        "memory_md_ok": False,
        "openclaw_md_ok": False,
        "skills_md_ok": False,
        "schedule_md_ok": False,
        "backups_md_ok": False,
        "migrations_md_ok": False,
        "runlog_md_ok": False,
        "job_message_ok": False,
    }

    # Perform checks only if files exist and content matches
    if memory_text is not None:
        checks["memory_md_ok"] = check_memory(memory_text, prefs)
    if openclaw_text is not None and backup_scope is not None:
        checks["openclaw_md_ok"] = check_openclaw(openclaw_text, prefs, backup_scope)
    if skills_text is not None:
        checks["skills_md_ok"] = check_skills(skills_text, prefs, skills_rows)
    if schedule_text is not None:
        checks["schedule_md_ok"] = check_schedule(schedule_text, prefs)
    if backups_text is not None:
        checks["backups_md_ok"] = check_backups(backups_text, skills_rows)
    if migrations_text is not None:
        checks["migrations_md_ok"] = check_migrations(migrations_text, migrations_records)
    if runlog_text is not None:
        checks["runlog_md_ok"] = check_runlog(runlog_text, prefs, skills_rows)
    if job_text is not None:
        checks["job_message_ok"] = check_jobmessage(job_text)

    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # No-op baseline: if output dir missing or empty, reward should be 0.0
    if not os.path.isdir(auto_dir) or not any(os.path.isfile(os.path.join(auto_dir, f)) for f in os.listdir(auto_dir) if not f.startswith(".")):
        reward = 0.0
        # ensure all false
        for k in checks.keys():
            checks[k] = False

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()