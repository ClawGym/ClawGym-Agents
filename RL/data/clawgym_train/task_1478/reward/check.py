import json
import os
import sys
from typing import List, Dict, Tuple

def read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def extract_section_lines(md_lines: List[str], heading: str) -> List[str]:
    # heading like "## Summary"
    start = None
    for i, line in enumerate(md_lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        return []
    end = len(md_lines)
    for j in range(start, len(md_lines)):
        if md_lines[j].startswith("## ") and md_lines[j].strip() != heading:
            end = j
            break
    return [l.rstrip("\n") for l in md_lines[start:end]]

def bullet_lines(section_lines: List[str]) -> List[str]:
    out = []
    for l in section_lines:
        ls = l.strip()
        if ls.startswith("- "):
            out.append(ls[2:].strip())
    return out

def normalized_single_line(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()

def unique_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out

def contains_case_insensitive(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Inputs
    diff_path = os.path.join(input_dir, "diff.json")
    pr_meta_path = os.path.join(input_dir, "pr_metadata.json")
    contributing_path = os.path.join(input_dir, "CONTRIBUTING.md")

    diff = read_json(diff_path) or {}
    pr_meta = read_json(pr_meta_path) or {}

    input_base = diff.get("base")
    input_head = diff.get("head")
    input_changed_files = diff.get("changedFiles", [])
    if not isinstance(input_changed_files, list):
        input_changed_files = []

    # Expected constants based on task spec
    EXPECTED_RECOMMENDED = [
        "pnpm build",
        "pnpm check",
        "pnpm test",
        "pnpm test:gateway",
        "pnpm format:docs:check",
        "pnpm lint:docs",
    ]
    EXPECTED_MAINTAINERS = [
        "Jos (@joshp123) / Ayaan Zaidi (@obviyus) — Telegram",
        "Josh Avant (@joshavant) / Jonathan Taylor (@visionik) — Gateway / ACP / core CLI",
        "Mariano Belinky (@mbelinky) / Vincent Koc (@vincentkoc) / Josh Avant (@joshavant) — Security/Auth",
    ]
    REQUIRED_WARNINGS = {
        "Keep the PR tightly scoped and explain impact/risk clearly; security/auth changes deserve extra review.",
        "Mark AI-assisted work in the PR title or description and state the testing level.",
        "Keep the PR focused: one bugfix/feature per PR; use Discussions first for new features or architecture changes.",
    }

    # Outputs to check
    plan_path = os.path.join(output_dir, "validation_plan.json")
    pr_body_path = os.path.join(output_dir, "pr_body.md")
    branch_path = os.path.join(output_dir, "branch.txt")
    maintainers_path = os.path.join(output_dir, "maintainers.txt")
    safety_path = os.path.join(output_dir, "git_safety_checklist.md")

    checks: Dict[str, bool] = {
        # validation_plan.json checks
        "plan_exists": False,
        "plan_has_required_keys": False,
        "plan_changed_files_match_input": False,
        "plan_recommended_commands_match_expected": False,
        "plan_maintainers_exact_expected": False,
        "plan_warnings_include_required": False,
        # pr_body.md checks
        "pr_body_exists": False,
        "pr_body_title_matches": False,
        "pr_body_has_required_headings": False,
        "pr_body_files_touched_include_all": False,
        "pr_body_validation_matches_plan": False,
        "pr_body_maintainers_section_includes_required": False,
        "pr_body_ai_assistance_section_correct": False,
        # branch.txt checks
        "branch_exists": False,
        "branch_format_and_keywords": False,
        # maintainers.txt checks
        "maintainers_txt_exists": False,
        "maintainers_txt_exact_expected": False,
        # git safety checklist checks
        "safety_exists": False,
        "safety_includes_current_branch_and_head": False,
        "safety_includes_backup_plan_and_yes": False,
        "safety_mentions_force_with_lease": False,
        "safety_lists_destructive_commands": False,
    }

    # validation_plan.json
    plan_data = None
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan_data = read_json(plan_path)
        if isinstance(plan_data, dict):
            required_keys = ["base", "head", "changedFiles", "recommendedCommands", "maintainersToConsider", "warnings"]
            if all(k in plan_data for k in required_keys):
                checks["plan_has_required_keys"] = True

            # changedFiles exact match with input
            out_changed_files = plan_data.get("changedFiles")
            if isinstance(out_changed_files, list) and out_changed_files == input_changed_files:
                checks["plan_changed_files_match_input"] = True

            # recommendedCommands exact match
            out_recommended = plan_data.get("recommendedCommands")
            if isinstance(out_recommended, list) and out_recommended == EXPECTED_RECOMMENDED:
                checks["plan_recommended_commands_match_expected"] = True

            # maintainers exact expected in order and only those
            out_maint = plan_data.get("maintainersToConsider")
            if isinstance(out_maint, list) and out_maint == EXPECTED_MAINTAINERS:
                checks["plan_maintainers_exact_expected"] = True

            # warnings include required set (order not enforced, superset allowed)
            out_warnings = plan_data.get("warnings")
            if isinstance(out_warnings, list):
                if all(any(w_req == w for w in out_warnings) for w_req in REQUIRED_WARNINGS):
                    checks["plan_warnings_include_required"] = True

    # pr_body.md
    pr_lines: List[str] = []
    if os.path.isfile(pr_body_path):
        checks["pr_body_exists"] = True
        pr_text = read_text(pr_body_path) or ""
        pr_lines = pr_text.splitlines()

        # Title must start with "# " and include title from input/pr_metadata.json exactly
        title = pr_meta.get("title", "")
        pr_title_line = ""
        for line in pr_lines:
            if line.strip():
                pr_title_line = line.strip()
                break
        if pr_title_line.startswith("# ") and pr_title_line == f"# {title}":
            checks["pr_body_title_matches"] = True

        # Required headings present
        required_headings = ["## Summary", "## Why", "## Files touched", "## Validation", "## Maintainer routing hints", "## AI assistance"]
        if all(any(l.strip() == h for l in pr_lines) for h in required_headings):
            checks["pr_body_has_required_headings"] = True

        # Files touched bullets include all changed files
        files_section = extract_section_lines(pr_lines, "## Files touched")
        files_bullets = bullet_lines(files_section)
        # Must include at least all changed files as separate bullet lines
        if input_changed_files and all(cf in files_bullets for cf in input_changed_files):
            checks["pr_body_files_touched_include_all"] = True
        elif not input_changed_files:
            # If no changed files, consider this trivially true
            checks["pr_body_files_touched_include_all"] = True

        # Validation bullets match exactly the plan's recommendedCommands
        val_section = extract_section_lines(pr_lines, "## Validation")
        val_bullets = bullet_lines(val_section)
        plan_cmds = plan_data.get("recommendedCommands") if isinstance(plan_data, dict) else None
        if isinstance(plan_cmds, list) and val_bullets == plan_cmds:
            checks["pr_body_validation_matches_plan"] = True

        # Maintainer routing hints include the three lines
        maint_section = extract_section_lines(pr_lines, "## Maintainer routing hints")
        maint_bullets = bullet_lines(maint_section)
        if all(m in maint_bullets for m in EXPECTED_MAINTAINERS):
            checks["pr_body_maintainers_section_includes_required"] = True

        # AI assistance section includes required lines
        ai_section = extract_section_lines(pr_lines, "## AI assistance")
        ai_bullets = bullet_lines(ai_section)
        required_ai_lines = [
            "AI-assisted: yes",
            "Testing level: lightly tested",
            "I reviewed the code and understand what it does.",
        ]
        if all(any(b.strip() == req for b in ai_bullets) for req in required_ai_lines):
            checks["pr_body_ai_assistance_section_correct"] = True

    # branch.txt
    if os.path.isfile(branch_path):
        checks["branch_exists"] = True
        branch_text = normalized_single_line(read_text(branch_path) or "")
        # single line check
        if "\n" not in branch_text:
            starts_fix = branch_text.startswith("fix/")
            has_gateway = contains_case_insensitive(branch_text, "gateway")
            has_telegram = contains_case_insensitive(branch_text, "telegram")
            if starts_fix and has_gateway and has_telegram:
                checks["branch_format_and_keywords"] = True

    # maintainers.txt
    if os.path.isfile(maintainers_path):
        checks["maintainers_txt_exists"] = True
        maint_text = read_text(maintainers_path) or ""
        maint_lines = [l.rstrip("\n") for l in maint_text.splitlines() if l.strip() != "" or True]
        # exact three lines match
        if maint_lines == EXPECTED_MAINTAINERS:
            checks["maintainers_txt_exact_expected"] = True

    # git_safety_checklist.md
    if os.path.isfile(safety_path):
        checks["safety_exists"] = True
        safety_text = read_text(safety_path) or ""
        st = safety_text

        # Must contain "Current branch:" and "HEAD" (e.g., HEAD or HEAD commit)
        if ("Current branch:" in st) and ("HEAD" in st):
            checks["safety_includes_current_branch_and_head"] = True

        # Must contain a "Backup plan" and phrase "explicit YES"
        if ("Backup plan" in st or "Backup plan:" in st) and ("explicit YES" in st):
            checks["safety_includes_backup_plan_and_yes"] = True

        # Must mention "git push --force-with-lease"
        if "git push --force-with-lease" in st:
            checks["safety_mentions_force_with_lease"] = True

        # Must list destructive commands exactly as names appear
        destructive_ok = all(cmd in st for cmd in ["git reset --hard", "git clean -fd", "git branch -D"])
        if destructive_ok:
            checks["safety_lists_destructive_commands"] = True

    # Compute reward as proportion of passed checks, baseline no-op -> 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure if no artifacts exist under output/, reward is 0.0
    # We consider "no-op baseline" if none of the primary artifacts exist
    primary_artifacts_exist = any(os.path.isfile(p) for p in [plan_path, pr_body_path, branch_path, maintainers_path, safety_path])
    if not primary_artifacts_exist:
        reward = 0.0

    # Print JSON result with "reward" first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()