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

def get_fenced_code_blocks(text):
    # Returns list of code block strings (content only, without fences)
    blocks = []
    lines = text.splitlines()
    in_block = False
    fence = None
    current = []
    for line in lines:
        if not in_block:
            m = re.match(r"^(```+)", line.strip())
            if m:
                in_block = True
                fence = m.group(1)
                current = []
            # else not code start
        else:
            # inside block
            if re.match(rf"^{re.escape(fence)}\s*$", line.strip()):
                blocks.append("\n".join(current))
                in_block = False
                fence = None
                current = []
            else:
                current.append(line)
    # If unclosed fence, ignore trailing
    return blocks

def last_non_empty_line(lines):
    for line in reversed(lines):
        if line.strip():
            return line
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    plan_rel = os.path.join("docs", "superpowers", "plans", "2026-04-17-import-contacts-cli.md")
    plan_path = os.path.join(output_dir, plan_rel)

    checks = {
        "has_plan_file": False,
        "header_has_title_in_first_40": False,
        "header_has_labels_in_first_40": False,
        "has_min_3_task_sections": False,
        "tdd_write_failing_test_ge3": False,
        "tdd_run_verify_fails_ge3": False,
        "tdd_write_minimal_code_ge3": False,
        "tdd_run_verify_passes_ge3": False,
        "tdd_commit_ge3": False,
        "has_pytest_test_codeblock": False,
        "has_pytest_run_selection_cmd": False,
        "has_git_commands_block": False,
        "has_file_mapping_src_and_tests": False,
        "no_prohibited_placeholders": False,
    }

    if not os.path.isfile(plan_path):
        # No-op baseline: reward must be 0.0
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    checks["has_plan_file"] = True

    text = read_text(plan_path) or ""
    # Safe guard: if file unreadable, treat as missing content
    if not text:
        # file exists but unreadable; treat all others as False
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # Header validation within first 40 non-empty lines
    non_empty = [ln for ln in text.splitlines() if ln.strip() != ""]
    first_40 = non_empty[:40]
    # Title starting with "# "
    checks["header_has_title_in_first_40"] = any(ln.lstrip().startswith("# ") for ln in first_40)
    # Labels Goal:, Architecture:, Tech Stack:
    lowered_first_40 = "\n".join(first_40).lower()
    checks["header_has_labels_in_first_40"] = all(lbl in lowered_first_40 for lbl in ["goal:", "architecture:", "tech stack:"])

    # Task sections: at least 3 headings starting with '### Task'
    task_headings = sum(1 for ln in text.splitlines() if re.match(r"^\s*###\s*task\b", ln.strip(), flags=re.IGNORECASE))
    checks["has_min_3_task_sections"] = task_headings >= 3

    # TDD steps phrases counts (case-insensitive, substring acceptable)
    low = text.lower()
    def count_occ(needle):
        return low.count(needle.lower())

    checks["tdd_write_failing_test_ge3"] = count_occ("write failing test") >= 3
    checks["tdd_run_verify_fails_ge3"] = count_occ("run to verify it fails") >= 3
    checks["tdd_write_minimal_code_ge3"] = count_occ("write minimal code") >= 3
    checks["tdd_run_verify_passes_ge3"] = count_occ("run to verify it passes") >= 3
    checks["tdd_commit_ge3"] = count_occ("commit") >= 3  # Accepts any "Commit" checklist step

    # Code blocks
    blocks = get_fenced_code_blocks(text)

    # Test code example: a code block with 'def test_' and 'assert ' in same block
    has_pytest_block = False
    for b in blocks:
        if re.search(r"\bdef\s+test_[A-Za-z0-9_]*\s*\(", b) and re.search(r"\bassert\s+", b):
            has_pytest_block = True
            break
    checks["has_pytest_test_codeblock"] = has_pytest_block

    # Run command sample: line showing pytest with node selection (either :: with tests/ path, or -k)
    has_run_cmd = False
    for ln in text.splitlines():
        l = ln.strip()
        if "pytest" in l:
            if "::" in l and "tests/" in l:
                has_run_cmd = True
                break
            if re.search(r"\b-k\b", l):
                has_run_cmd = True
                break
    checks["has_pytest_run_selection_cmd"] = has_run_cmd

    # Git commands: at least one fenced block containing 'git add' and 'git commit -m'
    has_git_block = False
    for b in blocks:
        if ("git add" in b) and re.search(r"git\s+commit\s+-m\s+", b):
            has_git_block = True
            break
    checks["has_git_commands_block"] = has_git_block

    # File mapping: at least one path under src/ and one under tests/ with .py extension
    has_src_py = re.search(r"\bsrc/[\w\-/\.]*\.py\b", text) is not None
    has_tests_py = re.search(r"\btests/[\w\-/\.]*\.py\b", text) is not None
    checks["has_file_mapping_src_and_tests"] = bool(has_src_py and has_tests_py)

    # Prohibited placeholders absent
    prohibited = ["tbd", "todo", "to be decided", "fill in later"]
    contains_prohibited = any(p in low for p in prohibited)
    checks["no_prohibited_placeholders"] = not contains_prohibited

    # Compute reward: 0.0 if no plan file; else average of all other checks
    check_keys_for_score = [k for k in checks.keys() if k != "has_plan_file"]
    if not checks["has_plan_file"]:
        reward = 0.0
    else:
        # If the plan exists but none other pass, score is 0
        passed = sum(1 for k in check_keys_for_score if checks[k])
        total = len(check_keys_for_score)
        reward = (passed / total) if total > 0 else 0.0

    # Ensure reward in [0,1]
    reward = max(0.0, min(1.0, reward))

    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()