import json
import os
import sys

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def normalize_exclusion(pattern):
    if pattern is None:
        return ""
    p = pattern.strip()
    if p.endswith("/**"):
        p = p[:-3]
    # remove trailing slashes for consistent prefix checks
    while p.endswith("/"):
        p = p[:-1]
    return p

def is_excluded(path, patterns):
    if not path:
        return False
    for raw in patterns:
        p = normalize_exclusion(raw)
        if not p:
            continue
        if path == p or path.startswith(p + "/"):
            return True
    return False

def parse_repo_state(state):
    added = state.get("added", []) or []
    modified = state.get("modified", []) or []
    deleted = state.get("deleted", []) or []
    renamed = state.get("renamed", []) or []
    # Normalize types to lists of strings (for added/modified/deleted)
    a = []
    for x in added:
        if isinstance(x, str):
            a.append(x)
    m = []
    for x in modified:
        if isinstance(x, str):
            m.append(x)
    d = []
    for x in deleted:
        if isinstance(x, str):
            d.append(x)
    # Renamed may be list of dicts with old/new, or two-item lists, or strings "old -> new"
    r = []
    for item in renamed:
        oldp = None
        newp = None
        if isinstance(item, dict):
            oldp = item.get("old") or item.get("from") or item.get("src")
            newp = item.get("new") or item.get("to") or item.get("dst") or item.get("dest")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            oldp, newp = item[0], item[1]
        elif isinstance(item, str) and "->" in item:
            parts = item.split("->", 1)
            oldp = parts[0].strip()
            newp = parts[1].strip()
        if isinstance(oldp, str) and isinstance(newp, str):
            r.append((oldp, newp))
    return a, m, d, r

def render_body(added, modified, deleted, renamed):
    lines = []
    # Added
    lines.append(f"Added({len(added)})")
    if added:
        for p in added:
            lines.append(f"- {p}")
    else:
        lines.append("- none")
    # blank line between sections
    lines.append("")
    # Modified
    lines.append(f"Modified({len(modified)})")
    if modified:
        for p in modified:
            lines.append(f"- {p}")
    else:
        lines.append("- none")
    lines.append("")
    # Deleted
    lines.append(f"Deleted({len(deleted)})")
    if deleted:
        for p in deleted:
            lines.append(f"- {p}")
    else:
        lines.append("- none")
    # Renamed only if any
    if renamed:
        lines.append("")
        lines.append(f"Renamed({len(renamed)})")
        for oldp, newp in renamed:
            lines.append(f"- {oldp} -> {newp}")
    return "\n".join(lines)

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def read_text_lines_strict_single(path):
    # Returns content stripped of trailing newline and a boolean indicating exactly one line
    raw = read_text(path)
    # Splitlines without keeping ends; this ignores trailing final newline
    lines = raw.splitlines()
    # Allow a single line; if empty file or more than one line, fail
    if len(lines) != 1:
        return raw, False
    return lines[0], True

def compare_exact(expected, actual_content):
    # Compare ignoring a possible trailing newline at EOF in actual
    # Normalize both by stripping single trailing newline if present
    exp = expected
    act = actual_content
    if act.endswith("\n"):
        act = act[:-1]
    if exp.endswith("\n"):
        exp = exp[:-1]
    return exp == act

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "commit_subject_exists": False,
        "commit_subject_single_line": False,
        "commit_subject_matches": False,
        "commit_body_exists": False,
        "commit_body_matches": False,
        "cron_job_exists": False,
        "cron_job_matches": False,
        "did_commit_exists": False,
        "did_commit_matches": False,
    }

    # Load inputs
    config_path = os.path.join(input_dir, "config.json")
    repo_state_path = os.path.join(input_dir, "repo_state.json")
    try:
        config = load_json(config_path)
        repo_state = load_json(repo_state_path)
    except Exception:
        # If inputs cannot be read, no positive reward should be granted
        result = {
            "reward": 0.0,
            **checks
        }
        print(json.dumps(result))
        return

    # Parse and filter changes
    excludes = config.get("BACKUP_EXCLUDES", []) or []
    if not isinstance(excludes, list):
        # If provided as string, try to accept comma-separated
        if isinstance(excludes, str):
            excludes = [s.strip() for s in excludes.split(",") if s.strip()]
        else:
            excludes = []

    added, modified, deleted, renamed = parse_repo_state(repo_state)

    # Apply exclusions (path prefix or exact match)
    filtered_added = sorted([p for p in added if not is_excluded(p, excludes)])
    filtered_modified = sorted([p for p in modified if not is_excluded(p, excludes)])
    filtered_deleted = sorted([p for p in deleted if not is_excluded(p, excludes)])
    filtered_renamed = sorted([(o, n) for (o, n) in renamed if not (is_excluded(o, excludes) or is_excluded(n, excludes))],
                              key=lambda x: f"{x[0]} -> {x[1]}")

    # Compute counts for subject (+A ~M -D) excluding renames
    A = len(filtered_added)
    M = len(filtered_modified)
    D = len(filtered_deleted)

    # Build expected commit subject
    ts = str(config.get("snapshot_timestamp", "")).strip()
    tz = str(config.get("tz_offset", "")).strip()
    expected_subject_line = f"backup: snapshot {ts} {tz} | +{A} ~{M} -{D}"

    # Build expected body
    expected_body = render_body(filtered_added, filtered_modified, filtered_deleted, filtered_renamed)

    # Build expected cron job content
    backup_remote = str(config.get("BACKUP_REMOTE", "origin"))
    backup_branch = str(config.get("BACKUP_BRANCH", ""))
    backup_tz = str(config.get("BACKUP_TZ", "UTC"))
    runtime_script = str(config.get("runtime_script", "")).strip()
    repo_root = str(config.get("repo_root", "")).strip()
    excludes_joined = ",".join([str(x) for x in excludes])

    cron_lines_expected = [
        f"BACKUP_REMOTE='{backup_remote}' \\",
        f"BACKUP_BRANCH='{backup_branch}' \\",
        f"BACKUP_TZ='{backup_tz}' \\",
        "BACKUP_AUTHOR_NAME='OpenClaw Backup' \\",
        "BACKUP_AUTHOR_EMAIL='backup@local' \\",
        f"BACKUP_EXCLUDES='{excludes_joined}' \\",
        f"bash -lc '{runtime_script} {repo_root}'",
    ]
    expected_cron = "\n".join(cron_lines_expected)

    # Build expected did_commit
    did_commit_expected = "DID_COMMIT=1" if (A > 0 or M > 0 or D > 0 or len(filtered_renamed) > 0) else "DID_COMMIT=0"

    # Paths to outputs
    subject_path = os.path.join(output_dir, "commit_subject.txt")
    body_path = os.path.join(output_dir, "commit_body.txt")
    cron_path = os.path.join(output_dir, "cron_job.txt")
    did_commit_path = os.path.join(output_dir, "did_commit.txt")

    # Check commit_subject.txt
    if os.path.isfile(subject_path):
        checks["commit_subject_exists"] = True
        try:
            subject_line, single = read_text_lines_strict_single(subject_path)
            if single:
                checks["commit_subject_single_line"] = True
                if subject_line == expected_subject_line:
                    checks["commit_subject_matches"] = True
        except Exception:
            pass

    # Check commit_body.txt
    if os.path.isfile(body_path):
        checks["commit_body_exists"] = True
        try:
            actual_body = read_text(body_path)
            if compare_exact(expected_body, actual_body):
                checks["commit_body_matches"] = True
        except Exception:
            pass

    # Check cron_job.txt
    if os.path.isfile(cron_path):
        checks["cron_job_exists"] = True
        try:
            actual_cron = read_text(cron_path)
            if compare_exact(expected_cron, actual_cron):
                checks["cron_job_matches"] = True
        except Exception:
            pass

    # Check did_commit.txt
    if os.path.isfile(did_commit_path):
        checks["did_commit_exists"] = True
        try:
            content, single = read_text_lines_strict_single(did_commit_path)
            # For did_commit, allow exactly one line only
            if single and content == did_commit_expected:
                checks["did_commit_matches"] = True
        except Exception:
            pass

    # Compute reward: average of core match checks
    core_checks = [
        checks["commit_subject_matches"],
        checks["commit_body_matches"],
        checks["cron_job_matches"],
        checks["did_commit_matches"],
    ]
    reward = sum(1.0 for c in core_checks if c) / float(len(core_checks)) if core_checks else 0.0

    # No-op baseline: if output dir missing or all required artifacts missing, reward must be 0.0
    required_exist = checks["commit_subject_exists"] or checks["commit_body_exists"] or checks["cron_job_exists"] or checks["did_commit_exists"]
    if not required_exist:
        reward = 0.0

    result = {
        "reward": reward,
        **checks
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()