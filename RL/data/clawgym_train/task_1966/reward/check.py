import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_diff_paths(diff_text):
    # Extract file paths from git diff lines
    # Accept paths from:
    # - diff --git a/path b/path
    # - --- a/path
    # - +++ b/path
    paths = set()
    if not diff_text:
        return paths
    for line in diff_text.splitlines():
        line = line.strip()
        if line.startswith("diff --git "):
            parts = line.split()
            # Expected: ["diff","--git","a/x","b/x"]
            for token in parts:
                if token.startswith("a/") or token.startswith("b/"):
                    paths.add(token[2:])
        elif line.startswith("+++ ") or line.startswith("--- "):
            token = line.split(maxsplit=1)[-1]
            # token like a/x or b/x or /dev/null
            if token.startswith("a/") or token.startswith("b/"):
                paths.add(token[2:])
    return paths

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def has_required_keys(item, required):
    return all(k in item for k in required)

def line_range_valid(s):
    if not isinstance(s, str):
        return False
    pat = re.compile(r"^[1-9][0-9]*-[1-9][0-9]*$")
    return bool(pat.match(s))

def is_single_line_nonempty(s):
    if not isinstance(s, str):
        return False
    return ("\n" not in s) and (s.strip() != "")

def long_enough_nonempty(s, min_len=11):
    if not isinstance(s, str):
        return False
    return len(s.strip()) >= min_len

def find_reviewer_bullets_in_section(trace_text):
    # Count bullet lines (- or *) in the "Reviewer" section specifically.
    # Heuristic:
    # - Identify line index of a line containing 'reviewer' but not 'meta'
    # - Segment ends at next line containing 'meta-reviewer' or 'builder' (case-insensitive)
    # - Count lines starting with "- " or "* " in that range
    if not trace_text:
        return 0
    lines = trace_text.splitlines()
    lower_lines = [ln.lower() for ln in lines]

    reviewer_idx = None
    for i, l in enumerate(lower_lines):
        if "reviewer" in l and "meta" not in l:
            reviewer_idx = i
            break
    if reviewer_idx is None:
        return 0

    # find end boundary
    end_idx = len(lines)
    for j in range(reviewer_idx + 1, len(lines)):
        lj = lower_lines[j]
        if "meta-reviewer" in lj or "meta reviewer" in lj or "builder" in lj:
            end_idx = j
            break

    bullet_count = 0
    for k in range(reviewer_idx, end_idx):
        stripped = lines[k].lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullet_count += 1
    return bullet_count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "review_json_exists": False,
        "review_json_valid": False,
        "review_is_array_1_3": False,
        "review_items_have_required_keys": False,
        "confidence_priority_high_exact": False,
        "file_paths_match_diff": False,
        "line_range_format_valid": False,
        "issue_single_line_nonempty": False,
        "impact_and_fix_length": False,
        "trace_md_exists": False,
        "trace_contains_sections": False,
        "trace_reviewer_bullets_at_least_3": False,
    }

    # Paths
    review_path = os.path.join(output_dir, "review.json")
    trace_path = os.path.join(output_dir, "trace.md")
    diff_path = os.path.join(input_dir, "diff.txt")

    # 1) review.json existence
    if os.path.isfile(review_path):
        checks["review_json_exists"] = True

        # 2) review.json valid JSON
        review_data = load_json(review_path)
        if review_data is not None:
            checks["review_json_valid"] = True

            # 3) Array size 1-3
            if isinstance(review_data, list) and 1 <= len(review_data) <= 3:
                checks["review_is_array_1_3"] = True

                # 4) items have required keys
                required_keys = ["file", "line_range", "issue", "impact", "suggested_fix", "confidence", "priority"]
                have_all_keys = all(isinstance(it, dict) and has_required_keys(it, required_keys) for it in review_data)
                if have_all_keys:
                    checks["review_items_have_required_keys"] = True

                    # 5) confidence and priority both exactly "high" for every item
                    conf_pri_ok = all(
                        it.get("confidence") == "high" and it.get("priority") == "high"
                        for it in review_data
                    )
                    if conf_pri_ok:
                        checks["confidence_priority_high_exact"] = True

                    # 6) file paths match diff
                    diff_text = read_text(diff_path)
                    diff_paths = parse_diff_paths(diff_text) if diff_text is not None else set()
                    if diff_paths:
                        file_ok = all(isinstance(it.get("file"), str) and it.get("file") in diff_paths for it in review_data)
                        if file_ok:
                            checks["file_paths_match_diff"] = True
                    # If diff_paths is empty or diff missing, we cannot validate positively; keep False

                    # 7) line_range pattern valid
                    lr_ok = all(line_range_valid(it.get("line_range")) for it in review_data)
                    if lr_ok:
                        checks["line_range_format_valid"] = True

                    # 8) issue single-line and non-empty
                    issue_ok = all(is_single_line_nonempty(it.get("issue")) for it in review_data)
                    if issue_ok:
                        checks["issue_single_line_nonempty"] = True

                    # 9) impact and suggested_fix long enough (>10 chars)
                    len_ok = all(
                        long_enough_nonempty(it.get("impact"), 11) and
                        long_enough_nonempty(it.get("suggested_fix"), 11)
                        for it in review_data
                    )
                    if len_ok:
                        checks["impact_and_fix_length"] = True

    # 10) trace.md exists
    if os.path.isfile(trace_path):
        checks["trace_md_exists"] = True
        trace_text = read_text(trace_path) or ""

        # 11) trace contains "Builder", "Reviewer", and "Meta-Reviewer" (case-insensitive)
        low = trace_text.lower()
        if ("builder" in low) and ("reviewer" in low) and (("meta-reviewer" in low) or ("meta reviewer" in low)):
            checks["trace_contains_sections"] = True

        # 12) at least three bullet points in reviewer section
        bullets = find_reviewer_bullets_in_section(trace_text)
        if bullets >= 3:
            checks["trace_reviewer_bullets_at_least_3"] = True

    # Compute reward
    # Enforce required artifacts: both review.json and trace.md must exist; otherwise reward = 0.0
    required_artifacts_present = checks["review_json_exists"] and checks["trace_md_exists"]

    # Fractional score across all checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not required_artifacts_present:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Output JSON with "reward" first
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()