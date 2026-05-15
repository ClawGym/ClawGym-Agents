import json
import os
import re
import sys

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def find_blocks(content, heading_regex):
    blocks = []
    matches = list(re.finditer(heading_regex, content, flags=re.MULTILINE))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        blocks.append(content[start:end])
    return blocks

def block_has_fields(block, required_fields):
    for rf in required_fields:
        if rf not in block:
            return False
    return True

def iso8601_utc_logged_lines(content):
    # Matches lines containing **Logged**: 2026-04-16T12:34:56Z
    return re.findall(r"\*\*Logged\*\*:\s*[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", content)

def has_case_insensitive_substring(s, needle):
    return needle.lower() in s.lower()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    feats_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    claude_path = os.path.join(output_dir, "CLAUDE.md")
    agents_path = os.path.join(output_dir, "AGENTS.md")

    checks = {}

    # Existence checks
    checks["exists_learnings"] = os.path.isfile(learnings_path)
    checks["exists_errors"] = os.path.isfile(errors_path)
    checks["exists_feature_requests"] = os.path.isfile(feats_path)
    checks["exists_claude"] = os.path.isfile(claude_path)
    checks["exists_agents"] = os.path.isfile(agents_path)

    # Initialize dependent checks
    checks.update({
        "learnings_has_3_entries": False,
        "learnings_entries_have_fields": False,
        "learnings_logged_timestamps_ge_3": False,
        "learnings_contains_required_strings": False,
        "learnings_has_see_also": False,
        "learnings_promoted_claude": False,
        "learnings_promoted_agents": False,
        "claude_mentions_pnpm_package_line": False,
        "agents_has_after_api_changes": False,
        "agents_has_generate_and_tsc_commands": False,
        "errors_has_2_entries": False,
        "errors_entries_have_fields": False,
        "errors_contains_permission_denied": False,
        "errors_contains_docker_related": False,
        "feature_has_1_entry": False,
        "feature_entry_has_fields": False,
    })

    # Process LEARNINGS.md
    if checks["exists_learnings"]:
        learnings_content = read_file(learnings_path) or ""
        # Heading pattern: ## [LRN-YYYYMMDD-XXX] <category>
        lrn_heading_re = r"^## \[LRN-\d{8}-[A-Za-z0-9]{3,}\]\s+[A-Za-z_]+"
        lrn_blocks = find_blocks(learnings_content, lrn_heading_re)
        # Count entries
        checks["learnings_has_3_entries"] = len(lrn_blocks) >= 3

        # Required fields within an entry
        required_learn_fields = [
            "**Logged**:",
            "**Priority**:",
            "**Status**:",
            "**Area**:",
            "### Summary",
            "### Details",
            "### Suggested Action",
            "### Metadata"
        ]
        blocks_with_all_fields = [b for b in lrn_blocks if block_has_fields(b, required_learn_fields)]
        checks["learnings_entries_have_fields"] = len(blocks_with_all_fields) >= 3

        # Logged ISO timestamps
        logged_matches = iso8601_utc_logged_lines(learnings_content)
        checks["learnings_logged_timestamps_ge_3"] = len(logged_matches) >= 3

        # Required substrings
        required_substrings = [
            "pnpm",
            "pnpm-lock.yaml",
            "X-Correlation-ID",
            "pnpm run generate:api",
            "pnpm tsc --noEmit"
        ]
        checks["learnings_contains_required_strings"] = all(s in learnings_content for s in required_substrings)

        # See Also line
        checks["learnings_has_see_also"] = "See Also: LRN-20250110-001" in learnings_content

        # Promoted entries checks
        promoted_claude = False
        promoted_agents = False
        for b in lrn_blocks:
            status_promoted = "**Status**: promoted" in b
            if status_promoted and "**Promoted**: CLAUDE.md" in b:
                promoted_claude = True
            if status_promoted and "**Promoted**: AGENTS.md" in b:
                promoted_agents = True
        checks["learnings_promoted_claude"] = promoted_claude
        checks["learnings_promoted_agents"] = promoted_agents

    # Process CLAUDE.md
    if checks["exists_claude"]:
        claude_content = read_file(claude_path) or ""
        # Look for a line that contains both 'Package' and 'pnpm' (case-insensitive)
        line_has_both = False
        for line in claude_content.splitlines():
            if ("package" in line.lower()) and ("pnpm" in line.lower()):
                line_has_both = True
                break
        checks["claude_mentions_pnpm_package_line"] = line_has_both

    # Process AGENTS.md
    if checks["exists_agents"]:
        agents_content = read_file(agents_path) or ""
        checks["agents_has_after_api_changes"] = "After API Changes" in agents_content
        # Commands: "pnpm run generate:api" and "pnpm tsc --NoEmit" (case-insensitive for --noEmit)
        has_generate = has_case_insensitive_substring(agents_content, "pnpm run generate:api")
        # Normalize case for noEmit check
        has_tsc = re.search(r"pnpm\s+tsc\s+--noemit", agents_content, flags=re.IGNORECASE) is not None
        checks["agents_has_generate_and_tsc_commands"] = has_generate and has_tsc

    # Process ERRORS.md
    if checks["exists_errors"]:
        errors_content = read_file(errors_path) or ""
        err_heading_re = r"^## \[ERR-\d{8}-[A-Za-z0-9]{3,}\]"
        err_blocks = find_blocks(errors_content, err_heading_re)
        checks["errors_has_2_entries"] = len(err_blocks) >= 2

        required_err_fields = [
            "**Logged**:",
            "**Priority**:",
            "**Status**:",
            "**Area**:",
            "### Summary",
            "### Error",
            "### Context",
            "### Suggested Fix",
            "### Metadata"
        ]
        # Count blocks that have all fields
        err_blocks_with_fields = [b for b in err_blocks if block_has_fields(b, required_err_fields)]
        checks["errors_entries_have_fields"] = len(err_blocks_with_fields) >= 2

        # Specific substrings
        checks["errors_contains_permission_denied"] = "Permission denied" in errors_content
        lower_err = errors_content.lower()
        checks["errors_contains_docker_related"] = any(
            phrase in lower_err for phrase in ["docker build", "no space left on device", "exec format error"]
        )

    # Process FEATURE_REQUESTS.md
    if checks["exists_feature_requests"]:
        feats_content = read_file(feats_path) or ""
        feat_heading_re = r"^## \[FEAT-\d{8}-[A-Za-z0-9]{3,}\]"
        feat_blocks = find_blocks(feats_content, feat_heading_re)
        checks["feature_has_1_entry"] = len(feat_blocks) >= 1

        required_feat_fields = [
            "**Logged**:",
            "**Priority**:",
            "**Status**:",
            "**Area**:",
            "### Requested Capability",
            "### User Context",
            "### Complexity Estimate",
            "### Suggested Implementation",
            "### Metadata"
        ]
        feat_block_has_fields = False
        if feat_blocks:
            feat_block_has_fields = block_has_fields(feat_blocks[0], required_feat_fields)
        checks["feature_entry_has_fields"] = feat_block_has_fields

    # Compute reward as fraction of checks passed
    # Only consider the concrete validation points defined above (not merely file existence? Both are included as checks)
    # If no checks pass, reward is 0.0
    bool_values = [v for v in checks.values()]
    passed = sum(1 for v in bool_values if v)
    total = len(bool_values)
    reward = (passed / total) if total > 0 and passed > 0 else 0.0

    # Print single JSON object
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()