import json
import os
import sys

def load_json_file(path):
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def normalize_snapshot(d):
    # Convert to dict[str,str], excluding workspace/ prefix
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        if not isinstance(k, str):
            continue
        # Exclude any path that begins with "workspace/"
        if k.startswith("workspace/"):
            continue
        # Values are text contents; coerce to string for exact text comparison
        out[k] = "" if v is None else str(v)
    return out

def compute_diff(current_map, latest_map):
    current_keys = set(current_map.keys())
    latest_keys = set(latest_map.keys())
    added = sorted(current_keys - latest_keys)
    deleted = sorted(latest_keys - current_keys)
    modified = sorted([k for k in (current_keys & latest_keys) if current_map[k] != latest_map[k]])
    return added, deleted, modified

def walk_rel_paths(root):
    rels = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            rels.append(rel)
    return rels

def file_contains_all_strings(path, strings):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return all(s in content for s in strings), content
    except Exception:
        return False, ""

def file_has_exact_single_line(path, expected_line):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        return len(lines) == 1 and lines[0] == expected_line
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks to False (artifact-dependent checks remain False unless verified)
    checks = {
        "expected_branch_changes": False,         # depends on input only, not counted toward reward
        "outputs_present": False,                 # whether any relevant output artifacts exist
        "branch_exclusive": False,                # ensures not both branch hallmark artifacts are present
        # Changes branch checks:
        "changes_branch_selected": False,         # backup dir exists and no no_changes.txt
        "backup_replica_complete": False,         # all files replicated with exact contents
        "backup_no_workspace_entries": False,     # no workspace/ entries under backup dir
        "changelog_header_present": False,        # changelog.md exists and has the date header
        "changelog_entries_complete": False,      # changelog has a line for each changed path with required label
        "changelog_no_workspace_entries": False,  # changelog has no workspace/ mentions
        "restore_preview_exists": False,          # restore preview file exists
        "restore_preview_lists_all_files": False, # preview lists all files to restore
        "restore_preview_warning": False,         # preview includes overwrite warning and ~/.openclaw
        # No-changes branch checks:
        "no_changes_branch_selected": False,      # no backup dir and has no_changes.txt
        "no_changes_exact_content": False,        # file content exactly "no changes"
        # Optional informational checks (not scored):
        "changelog_has_bullets": False,           # at least some entries look like bullets "- "
    }

    # Load inputs
    current_path = os.path.join(input_dir, "current_openclaw.json")
    latest_path = os.path.join(input_dir, "latest_backup.json")
    current_raw = load_json_file(current_path)
    latest_raw = load_json_file(latest_path)

    # If inputs are missing or invalid, reward must remain 0.0, but still output JSON.
    current_map = normalize_snapshot(current_raw if isinstance(current_raw, dict) else {})
    latest_map = normalize_snapshot(latest_raw if isinstance(latest_raw, dict) else {})
    added, deleted, modified = compute_diff(current_map, latest_map)
    has_changes = bool(added or deleted or modified)
    checks["expected_branch_changes"] = has_changes

    # Output artifact locations
    backup_root = os.path.join(output_dir, "backup")
    date_str = "2026-03-12"
    backup_date_dir = os.path.join(backup_root, date_str)
    changelog_path = os.path.join(backup_root, "changelog.md")
    sentinel_no_changes = os.path.join(backup_root, "no_changes.txt")
    restore_preview_path = os.path.join(backup_root, f"restore-{date_str}-preview.txt")

    # Determine presence of outputs
    # Consider outputs present if any of the branch hallmark files/dirs exist
    outputs_present = False
    if os.path.isdir(backup_date_dir) or os.path.isfile(changelog_path) or os.path.isfile(restore_preview_path) or os.path.isfile(sentinel_no_changes):
        outputs_present = True
    checks["outputs_present"] = outputs_present

    # Mutual exclusivity check: both hallmark artifacts present is invalid
    has_backup_dir = os.path.isdir(backup_date_dir)
    has_no_changes_file = os.path.isfile(sentinel_no_changes)
    checks["branch_exclusive"] = not (has_backup_dir and has_no_changes_file)

    # Evaluate branches
    if has_changes:
        # Expect changes branch
        # Correct branch selection: backup dir exists and no no_changes sentinel
        if has_backup_dir and not has_no_changes_file:
            checks["changes_branch_selected"] = True

        # Verify backup replica completeness and exclusion of workspace entries
        if has_backup_dir:
            # For each non-workspace file in current_map, verify existence and exact content
            all_ok = True
            for rel_path, expected_content in current_map.items():
                target_path = os.path.join(backup_date_dir, rel_path)
                if not os.path.isfile(target_path):
                    all_ok = False
                    break
                try:
                    with open(target_path, "r", encoding="utf-8") as f:
                        got = f.read()
                    if got != expected_content:
                        all_ok = False
                        break
                except Exception:
                    all_ok = False
                    break
            checks["backup_replica_complete"] = all_ok

            # Ensure no workspace/ entries inside backup_date_dir
            no_ws = True
            for rel in walk_rel_paths(backup_date_dir):
                if rel.startswith("workspace/"):
                    no_ws = False
                    break
            checks["backup_no_workspace_entries"] = no_ws

        # Changelog checks
        if os.path.isfile(changelog_path):
            try:
                with open(changelog_path, "r", encoding="utf-8") as f:
                    changelog = f.read()
            except Exception:
                changelog = ""
            # Header presence with date
            lines = changelog.splitlines()
            header_ok = any(("## " in line and date_str in line) for line in lines)
            checks["changelog_header_present"] = header_ok

            # No workspace mentions
            checks["changelog_no_workspace_entries"] = ("workspace/" not in changelog)

            # Entries complete: for each changed path, a line includes the path and contains one of labels
            change_paths = added + deleted + modified
            labels = ("modified", "added", "deleted")
            found_for_all = True
            bullets_detected = True if change_paths else False  # if there are changes, require bullets for at least one entry
            for p in change_paths:
                found_line = False
                for line in lines:
                    if p in line:
                        lcline = line.lower()
                        if any(lbl in lcline for lbl in labels):
                            found_line = True
                            # track bullet style
                            if not (line.lstrip().startswith("- ") or line.lstrip().startswith("* ")):
                                bullets_detected = False if bullets_detected is not True else False
                            else:
                                # if at least one bullet found, keep True; we only want to mark True if all entries are bulleted
                                pass
                        # continue checking other lines in case there are multiple
                if not found_line:
                    found_for_all = False
                    break
            checks["changelog_entries_complete"] = found_for_all
            # Optional informational: consider it True only if every changed path line appears to be bulleted
            # If there are no changes, keep False (not applicable)
            if change_paths:
                # Re-evaluate bullets: all changed entries should be on some bulleted line
                all_bulleted = True
                for p in change_paths:
                    bulleted_for_p = False
                    for line in lines:
                        if p in line and (line.lstrip().startswith("- ") or line.lstrip().startswith("* ")):
                            # Also require label on same line to match primary requirement
                            if any(lbl in line.lower() for lbl in labels):
                                bulleted_for_p = True
                                break
                    if not bulleted_for_p:
                        all_bulleted = False
                        break
                checks["changelog_has_bullets"] = all_bulleted

        # Restore preview checks
        if os.path.isfile(restore_preview_path):
            checks["restore_preview_exists"] = True
            ok_all, content = file_contains_all_strings(restore_preview_path, [date_str])
            # Also ensure it lists all files that would be restored and includes overwrite warning and "~/.openclaw"
            if ok_all:
                lists_all = all((p in content) for p in current_map.keys())
                # ensure no workspace mentions
                lists_all = lists_all and ("workspace/" not in content)
                checks["restore_preview_lists_all_files"] = lists_all
                checks["restore_preview_warning"] = ("overwrite" in content.lower() and "~/.openclaw" in content)
            else:
                # Even if date not found, still check overwrite and paths for completeness of reporting
                checks["restore_preview_lists_all_files"] = False
                checks["restore_preview_warning"] = False

    else:
        # Expect no-changes branch
        # Correct branch selection: no backup dir and has sentinel file
        if (not has_backup_dir) and has_no_changes_file:
            checks["no_changes_branch_selected"] = True
        # Sentinel content exactly "no changes"
        if has_no_changes_file:
            checks["no_changes_exact_content"] = file_has_exact_single_line(sentinel_no_changes, "no changes")

    # Compute reward as weighted sum depending on expected branch
    reward = 0.0
    if not checks["outputs_present"]:
        reward = 0.0
    else:
        if has_changes:
            # weights for changes branch
            weights = {
                "changes_branch_selected": 0.10,
                "backup_replica_complete": 0.35,
                "backup_no_workspace_entries": 0.05,
                "changelog_header_present": 0.10,
                "changelog_entries_complete": 0.20,
                "changelog_no_workspace_entries": 0.05,
                "restore_preview_exists": 0.05,
                "restore_preview_lists_all_files": 0.05,
                "restore_preview_warning": 0.05,
                "branch_exclusive": 0.05,
            }
            for k, w in weights.items():
                if checks.get(k, False):
                    reward += w
        else:
            # weights for no-changes branch
            weights = {
                "no_changes_branch_selected": 0.80,  # combines absence of dir and presence of sentinel
                "no_changes_exact_content": 0.20,
            }
            # Also ensure exclusivity by requiring no backup dir in "no_changes_branch_selected"
            for k, w in weights.items():
                if checks.get(k, False):
                    reward += w

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Build result with "reward" first
    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object as the last non-empty line
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()