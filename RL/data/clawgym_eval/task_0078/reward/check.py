import json
import os
import sys

def to_posix(rel_path: str) -> str:
    return rel_path.replace(os.sep, "/")

def list_files(root):
    files = []
    for base, dirs, fnames in os.walk(root):
        for fn in fnames:
            full = os.path.join(base, fn)
            rel = os.path.relpath(full, root)
            files.append(to_posix(rel))
    return files

def file_bytes_equal(p1, p2):
    try:
        with open(p1, "rb") as f1, open(p2, "rb") as f2:
            b1 = f1.read()
            b2 = f2.read()
        return b1 == b2
    except Exception:
        return False

def read_text_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def read_text_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\r\n") for line in f.readlines()]

def find_changelog_section(lines, header_line):
    # Returns (start_idx, end_idx_exclusive)
    # Find exact header line match, and section until next "## " or end
    start = None
    for i, line in enumerate(lines):
        if line == header_line:
            start = i
            break
    if start is None:
        return None, None
    # Find next header
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return start, end

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "wrote_backup_config": False,
        "backup_dir_exists": False,
        "mirrors_set_exact": False,
        "openclaw_json_copied": False,
        "notes_txt_copied": False,
        "extension_skill_copied": False,
        "workspace_excluded_backup": False,
        "changelog_header": False,
        "changelog_bullets": False,
        "workspace_excluded_changelog": False,
        "no_writes_outside_output": False  # unscored
    }

    # Read expected date and time from inputs
    try:
        date_path = os.path.join(input_dir, "backup_date.txt")
        time_path = os.path.join(input_dir, "backup_time.txt")
        with open(date_path, "r", encoding="utf-8") as f:
            date_str = f.read().strip()
        with open(time_path, "r", encoding="utf-8") as f:
            time_str = f.read().strip()
    except Exception:
        date_str = None
        time_str = None

    # 1) Check backup.json content
    try:
        backup_cfg_path = os.path.join(output_dir, "openclaw", "backup.json")
        if os.path.isfile(backup_cfg_path):
            with open(backup_cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict) and cfg.get("backup_location") == "output/backup_store":
                checks["wrote_backup_config"] = True
    except Exception:
        pass

    # Expected backup dir path
    expected_backup_dir = None
    if date_str:
        expected_backup_dir = os.path.join(output_dir, "backup_store", date_str)
        if os.path.isdir(expected_backup_dir):
            checks["backup_dir_exists"] = True

    # 2) Verify backup mirrors current excluding workspace
    current_root = os.path.join(input_dir, "openclaw_current")
    # Build expected set
    expected_set = set()
    if os.path.isdir(current_root):
        for base, dirs, files in os.walk(current_root):
            for fn in files:
                full = os.path.join(base, fn)
                rel = os.path.relpath(full, current_root)
                rel_posix = to_posix(rel)
                # Exclude top-level workspace subtree
                if rel_posix == "workspace" or rel_posix.startswith("workspace/"):
                    continue
                expected_set.add(rel_posix)

    actual_set = set()
    if expected_backup_dir and os.path.isdir(expected_backup_dir):
        for base, dirs, files in os.walk(expected_backup_dir):
            for fn in files:
                full = os.path.join(base, fn)
                rel = os.path.relpath(full, expected_backup_dir)
                rel_posix = to_posix(rel)
                actual_set.add(rel_posix)

        # Set equality check
        if expected_set and actual_set == expected_set:
            checks["mirrors_set_exact"] = True

        # Workspace exclusion in backup
        if all(not p.startswith("workspace/") and p != "workspace" for p in actual_set):
            checks["workspace_excluded_backup"] = True

        # Content checks for specific files
        # - openclaw.json
        in_openclaw_json = os.path.join(current_root, "openclaw.json")
        out_openclaw_json = os.path.join(expected_backup_dir, "openclaw.json")
        if os.path.isfile(in_openclaw_json) and os.path.isfile(out_openclaw_json):
            if file_bytes_equal(in_openclaw_json, out_openclaw_json):
                checks["openclaw_json_copied"] = True

        # - notes.txt
        in_notes = os.path.join(current_root, "notes.txt")
        out_notes = os.path.join(expected_backup_dir, "notes.txt")
        if os.path.isfile(in_notes) and os.path.isfile(out_notes):
            if file_bytes_equal(in_notes, out_notes):
                checks["notes_txt_copied"] = True

        # - extensions/feishu/skills/feishu-doc/SKILL.md
        rel_ext = os.path.join("extensions", "feishu", "skills", "feishu-doc", "SKILL.md")
        in_ext = os.path.join(current_root, rel_ext)
        out_ext = os.path.join(expected_backup_dir, rel_ext)
        if os.path.isfile(in_ext) and os.path.isfile(out_ext):
            if file_bytes_equal(in_ext, out_ext):
                checks["extension_skill_copied"] = True

    # 3) Changelog checks
    try:
        changelog_path = os.path.join(output_dir, "backup_store", "changelog.md")
        if os.path.isfile(changelog_path) and date_str and time_str:
            lines = read_text_lines(changelog_path)
            header_line = f"## {date_str} {time_str}"
            start, end = find_changelog_section(lines, header_line)
            if start is not None:
                checks["changelog_header"] = True
                section_lines = lines[start+1:end]
                # Collect bullet lines
                bullets = [ln.strip() for ln in section_lines if ln.strip().startswith("- ")]
                # Required bullets
                required_bullets = {
                    "- openclaw.json (modified)",
                    "- extensions/feishu/skills/feishu-doc/SKILL.md (added)",
                    "- agents/bot/config.yaml (deleted)"
                }
                if required_bullets.issubset(set(bullets)):
                    checks["changelog_bullets"] = True
                # Workspace exclusion in changelog section
                if all(not b[2:].startswith("workspace/") for b in bullets):
                    checks["workspace_excluded_changelog"] = True
    except Exception:
        pass

    # 4) No writes outside output (unscored)
    try:
        top_entries = []
        if os.path.isdir(workspace_root):
            top_entries = [e for e in os.listdir(workspace_root) if e not in (".", "..")]
        allowed = {"input", "output", "reward"}
        extras = [e for e in top_entries if e not in allowed and not e.startswith(".")]
        checks["no_writes_outside_output"] = (len(extras) == 0)
    except Exception:
        checks["no_writes_outside_output"] = False

    # Compute reward (only scored checks). If no scored checks passed, reward must be 0.0
    scored_keys = [
        "wrote_backup_config",
        "backup_dir_exists",
        "mirrors_set_exact",
        "openclaw_json_copied",
        "notes_txt_copied",
        "extension_skill_copied",
        "workspace_excluded_backup",
        "changelog_header",
        "changelog_bullets",
        "workspace_excluded_changelog",
    ]
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    total = len(scored_keys)
    reward = (passed / total) if passed > 0 else 0.0

    # Print final JSON
    result = {"reward": reward}
    # Ensure deterministic ordering of keys is not required, just include all
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()