# Subagent-Driven Development Enablement – Implementation Plan

Author: Platform Engineering  
Scope: Establish lightweight tooling and templates that support Subagent-Driven Development (SDD) for executing plans with per-task workers and two-stage reviews.  
Session policy: All tasks are independent and executed within the same session, one at a time, with review gates enforced (spec first, then code quality).

## Background

We are formalizing the SDD workflow in this repository by:
- Providing a TodoWrite tracker library + CLI to manage per-task status.
- Adding reviewer templates to standardize code and spec reviews.
- Shipping a safe Git worktree helper to ensure implementers never work directly on protected branches.

These tasks are designed to be independent and can be completed in any order—but must be run sequentially in this session (no parallel workers) per policy.

## Task List

### Task T1 — Implement TodoWrite library and CLI
Full text:
Create a minimal, dependency-free TodoWrite tracking system to manage per-task status across the SDD workflow.

Requirements:
- Provide a Python 3.11 library at tools/todowrite.py with:
  - A JSON data model (dictionary) keyed by task_id with fields:
    - implementer_done (bool)
    - spec_review_pass (bool)
    - code_quality_pass (bool)
    - complete (bool)
  - Functions:
    - create_tracker(task_ids: list[str]) -> dict
    - update_status(tracker: dict, task_id: str, **kwargs) -> dict
    - is_complete(tracker: dict, task_id: str) -> bool
    - all_complete(tracker: dict) -> bool
  - Strictly prohibit extra fields or keys beyond the four booleans listed above.
- Provide a CLI at tools/todowrite_cli.py with subcommands:
  - init --tasks <comma-separated-ids> --out <path>
  - update --in <path> --task <id> --set <key=value>[,<key=value>...]
  - show --in <path>
  - Behavior details:
    - init creates a new JSON file with all four booleans set to false for each task.
    - update toggles one or more keys per task and writes back the JSON.
    - show prints the entire JSON object to stdout, with tasks sorted by id ascending.
    - All error messages go to stderr; exit non-zero on invalid task_id or invalid key.
- Testing:
  - Add tests/test_todowrite.py using pytest with at least 3 tests:
    - test_init_creates_all_false
    - test_update_toggles_values
    - test_update_invalid_task_exits_nonzero (simulate via subprocess on CLI or unit-level check)
- Documentation:
  - Add tools/README.md describing the schema, CLI usage, and examples (one-liners).
- Constraints:
  - No external dependencies.
  - Keep the code small and readable. Avoid over-building (YAGNI).
  - Only the specified keys may exist in the tracker; adding extra fields fails tests.

Acceptance Criteria:
1) Running `python3 tools/todowrite_cli.py init --tasks T1,T2 --out output/todo.json` produces a JSON file with entries for T1 and T2, all booleans false.
2) Running `python3 tools/todowrite_cli.py update --in output/todo.json --task T1 --set implementer_done=true,spec_review_pass=true` updates only those keys for T1.
3) Running `python3 tools/todowrite_cli.py show --in output/todo.json` prints valid JSON to stdout, tasks sorted by id.
4) Invalid task_id in update causes non-zero exit and an error message on stderr.
5) tests/test_todowrite.py passes locally (3 tests minimum).
6) No extra keys are present beyond the four booleans.

---

### Task T2 — Add standardized code and spec review templates
Full text:
Create standardized markdown templates for code-quality and spec-compliance reviewers so subagents can use consistent formats.

Requirements:
- Create requesting-code-review/code-reviewer.md with the following exact top-level sections (in order):
  1) WHAT_WAS_IMPLEMENTED
  2) PLAN_OR_REQUIREMENTS
  3) BASE_SHA
  4) HEAD_SHA
  5) STRENGTHS
  6) ISSUES
     - Under ISSUES, include subheadings for: CRITICAL, IMPORTANT, MINOR
  7) ASSESSMENT
- Create requesting-code-review/spec-reviewer.md with these exact top-level sections (in order):
  1) WHAT_WAS_REQUESTED
  2) IMPLEMENTER_REPORT
  3) METHOD
     - METHOD must state: code-inspection
  4) MISSING
  5) EXTRA
  6) MISUNDERSTANDINGS
  7) DECISION
- Content guidelines:
  - Include a brief one-line instruction under each section guiding what content belongs there.
  - Wrap at <= 100 characters per line where practical.
  - Do not add any additional sections or re-order.
- Add requesting-code-review/README.md summarizing how implementers and reviewers use these templates.

Acceptance Criteria:
1) Both markdown files exist with exactly the required section headings in the specified order.
2) spec-reviewer.md contains a METHOD section that explicitly says "code-inspection".
3) README.md provides at least one example usage snippet for each template.
4) No extra sections beyond those listed are present.
5) Lines are generally <= 100 characters.

---

### Task T3 — Safe Git worktree helper (requires base-branch confirmation)
Full text:
Create a portable bash script to set up isolated worktrees for each task that never start work on
protected branches. The script must guard against using "main" or "master" and must default to a
base branch that is explicitly confirmed by the controller before implementation.

Requirements:
- Create scripts/worktree.sh with:
  - Shebang: `#!/usr/bin/env bash`
  - `set -euo pipefail`
  - Flags:
    - --branch <feature-branch> (required; cannot be "main" or "master")
    - --base <base-branch> (optional; if omitted, use the confirmed default base)
    - --path <directory> (optional; default: ./worktrees/<branch>)
    - --dry-run (optional; print actions without executing)
  - Behavior:
    - Refuse to proceed if --branch is "main" or "master" (case-insensitive).
    - If --base is omitted, use the confirmed default base branch value for this repository.
    - Prints the base branch it will use in the first line of `--help` output exactly as:
      "Default base branch: <value>"
    - With --dry-run, print the exact git commands that would be run, no side effects.
  - Help:
    - `scripts/worktree.sh --help` prints usage, flags, and the default base branch line.
- Testing:
  - Add scripts/test_worktree.sh that:
    - Invokes `scripts/worktree.sh --help` and asserts the default base branch line is present.
    - Runs a dry-run example and asserts that neither "main" nor "master" can be used.
- Constraints:
  - POSIX-compatible bash, no external dependencies.
  - Must not create or modify a worktree when --dry-run is provided.

Ambiguity to Confirm (must ask before implementation):
- The default base branch value is undecided in this plan. Controller must confirm whether it is
  "develop" or another branch name before you set it in the script help and default behavior.

Acceptance Criteria:
1) `scripts/worktree.sh --help` begins with "Default base branch: <value>" that matches the confirmed base.
2) Passing `--branch main` or `--branch master` causes a failure with a clear error message.
3) `--dry-run` prints the git commands without executing them.
4) `scripts/test_worktree.sh` verifies the help output and the guard against protected branches.
5) If `--base` is omitted, the script uses the confirmed default base.

## Non-Functional Constraints (apply to all tasks)

- Simplicity: Only implement what is requested, nothing more.
- Portability: Python 3.11 for libs/CLIs; Bash for scripts (no external deps).
- Documentation: Provide minimal, clear READMEs where requested.
- Reviews: Expect spec-compliance first, then code-quality review.

## Deliverables

- Tools and scripts as described above.
- Tests and minimal documentation per task.
- No changes to protected branches. Work should be performed on a feature branch.

## Notes

- For Task T3, do not proceed without explicit confirmation of the default base branch.
- All tasks are independent. Execute one at a time with review gates per SDD.