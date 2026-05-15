import json
import os
import re
import sys

def read_text(fp):
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def split_lines(s):
    return s.splitlines() if s is not None else []

def non_empty_lines(lines):
    return [l for l in lines if l.strip() != ""]

def parse_changed_files_from_stat(stat_text):
    files = []
    for line in split_lines(stat_text):
        if '|' in line:
            left = line.split('|', 1)[0].strip()
            if left:
                files.append(left)
    return files

def detect_commit_type(files, diff_text):
    # Priority:
    # a) test if any filename contains "test" or "spec" (case-insensitive)
    lower_files = [f.lower() for f in files]
    if any(('test' in f or 'spec' in f) for f in lower_files):
        return "test"
    # b) docs if every filename is *.md or contains "readme" or "doc" (case-insensitive)
    if files and all(f.endswith('.md') or ('readme' in f.lower()) or ('doc' in f.lower()) for f in files):
        return "docs"
    # c) fix if diff has a line starting with "+ " and a line starting with "- " and files <= 3
    lines = split_lines(diff_text or "")
    has_plus_space = any(l.startswith("+ ") for l in lines)
    has_minus_space = any(l.startswith("- ") for l in lines)
    if has_plus_space and has_minus_space and len(files) <= 3:
        return "fix"
    # d) otherwise feat
    return "feat"

def detect_scope(files):
    if not files:
        return None
    top_levels = [f.split('/', 1)[0] for f in files]
    unique = set(top_levels)
    return top_levels[0] if len(unique) == 1 else None

def count_added_removed(diff_text):
    lines = split_lines(diff_text or "")
    added = sum(1 for l in lines if l.startswith('+') and not l.startswith('++'))
    removed = sum(1 for l in lines if l.startswith('-') and not l.startswith('--'))
    return added, removed

def commit_expected(input_dir):
    stat_path = os.path.join(input_dir, "commit_diff_stat.txt")
    diff_path = os.path.join(input_dir, "commit_diff.txt")
    stat_text = read_text(stat_path) or ""
    diff_text = read_text(diff_path) or ""

    files = parse_changed_files_from_stat(stat_text)
    ctype = detect_commit_type(files, diff_text)
    scope = detect_scope(files)
    added, removed = count_added_removed(diff_text)

    if len(files) == 1:
        basename = os.path.basename(files[0])
        subject = f"update {basename}"
    else:
        subject = f"update {len(files)} files (+{added}/-{removed})"

    if scope:
        message = f"{ctype}({scope}): {subject}"
    else:
        message = f"{ctype}: {subject}"
    # Truncate to max 72 characters
    message = message[:72]

    expected = {
        "message": message,
        "type": ctype,
        "scope": scope if scope is not None else None,
        "files": len(files)
    }
    return expected

def pr_expected(input_dir):
    branch_path = os.path.join(input_dir, "current_branch.txt")
    base_path = os.path.join(input_dir, "base_branch.txt")
    log_path = os.path.join(input_dir, "pr_log_oneline.txt")
    stat_path = os.path.join(input_dir, "pr_diff_stat.txt")

    branch = (read_text(branch_path) or "").strip()
    base = (read_text(base_path) or "").strip()
    log_text = read_text(log_path) or ""
    stat_text = read_text(stat_path) or ""

    # Title: replace '-', '_', '/' with space, then remove leading "feature ", "fix ", or "chore " (case-sensitive)
    title = branch.replace('-', ' ').replace('_', ' ').replace('/', ' ')
    if title.startswith("feature "):
        title = title[len("feature "):]
    elif title.startswith("fix "):
        title = title[len("fix "):]
    elif title.startswith("chore "):
        title = title[len("chore "):]

    log_lines = non_empty_lines(split_lines(log_text))
    commits_count = len(log_lines)
    summary_items = []
    for l in log_lines:
        # take substring starting at index 8 (drop first 8 chars)
        msg = l[8:] if len(l) >= 8 else ""
        summary_items.append("- " + msg)
    summary = "\n".join(summary_items)

    files_changed = sum(1 for l in split_lines(stat_text) if '|' in l)

    expected = {
        "branch": branch,
        "baseBranch": base,
        "title": title,
        "commits": commits_count,
        "summary": summary,
        "filesChanged": files_changed
    }
    return expected

def changelog_expected(input_dir):
    log_path = os.path.join(input_dir, "changelog_log_oneline.txt")
    log_text = read_text(log_path) or ""
    features = []
    fixes = []
    docs = []
    other = []

    for l in non_empty_lines(split_lines(log_text)):
        msg = l[8:] if len(l) >= 8 else ""
        low = msg.lower()
        if low.startswith("feat"):
            features.append(msg)
        elif low.startswith("fix"):
            fixes.append(msg)
        elif low.startswith("docs") or low.startswith("doc"):
            docs.append(msg)
        else:
            other.append(msg)

    expected = {
        "features": features,
        "fixes": fixes,
        "docs": docs,
        "other": other
    }
    return expected

def branch_expected(input_dir):
    desc_path = os.path.join(input_dir, "branch_description.txt")
    desc = read_text(desc_path) or ""
    # Determine prefix
    if re.search(r'(fix|bug|patch)', desc, flags=re.IGNORECASE):
        prefix = "fix"
    elif re.search(r'(doc)', desc, flags=re.IGNORECASE):
        prefix = "docs"
    else:
        prefix = "feature"
    # Create slug
    slug = re.sub(r'[^a-z0-9]+', '-', desc.lower())
    slug = slug[:50]
    slug = slug.strip('-')
    if slug == "":
        slug = "unnamed"
    return f"{prefix}/{slug}"

def load_and_canonicalize_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            obj = json.load(f)
        # Canonical string: sorted keys, no spaces
        return json.dumps(obj, sort_keys=True, separators=(',', ':')), obj
    except Exception:
        return None, None

def canonicalize_obj(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "commit_ok": False,
        "pr_ok": False,
        "changelog_ok": False,
        "branch_ok": False
    }

    # Compute expected artifacts
    expected_commit = commit_expected(input_dir)
    expected_pr = pr_expected(input_dir)
    expected_changelog = changelog_expected(input_dir)
    expected_branch = branch_expected(input_dir)

    # Verify commit.json
    commit_out_path = os.path.join(output_dir, "commit.json")
    if os.path.isfile(commit_out_path):
        actual_str, actual_obj = load_and_canonicalize_json(commit_out_path)
        if actual_str is not None:
            expected_str = canonicalize_obj(expected_commit)
            # Exact string equality after canonicalization
            if actual_str == expected_str:
                checks["commit_ok"] = True

    # Verify pr.json
    pr_out_path = os.path.join(output_dir, "pr.json")
    if os.path.isfile(pr_out_path):
        actual_str, actual_obj = load_and_canonicalize_json(pr_out_path)
        if actual_str is not None:
            expected_str = canonicalize_obj(expected_pr)
            if actual_str == expected_str:
                checks["pr_ok"] = True

    # Verify changelog.json
    changelog_out_path = os.path.join(output_dir, "changelog.json")
    if os.path.isfile(changelog_out_path):
        actual_str, actual_obj = load_and_canonicalize_json(changelog_out_path)
        if actual_str is not None:
            # Enforce exactly the four keys by canonical comparison
            expected_str = canonicalize_obj(expected_changelog)
            if actual_str == expected_str:
                checks["changelog_ok"] = True

    # Verify branch.txt
    branch_out_path = os.path.join(output_dir, "branch.txt")
    if os.path.isfile(branch_out_path):
        try:
            with open(branch_out_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Normalize by stripping trailing newlines and spaces
            content_norm = content.strip()
            expected_norm = expected_branch.strip()
            if content_norm == expected_norm:
                checks["branch_ok"] = True
        except Exception:
            pass

    total = sum(1 for k, v in checks.items() if v)
    reward = total / 4.0 if total > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()