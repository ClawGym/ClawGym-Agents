# Scene and Policies

This repository hosts enablement for the Subagent-Driven Development (SDD) workflow. Use this
context to guide implementation, reviews, and branch hygiene.

## Branch and Git Policies

- Protected branches: main and master are protected and may not be used for direct development.
- Default base branch for feature work: develop.
- Feature branches should follow: feature/sdd-<short-desc>
- Never start implementation on main/master.
- Each independent task must be executed on an isolated worktree (or equivalent) derived from the
  base branch.
- Commit messages should be descriptive and reference the task id (e.g., "T1: add todowrite init").

## Review Gates (Mandatory Order)

- For every task, run a two-stage review:
  1) Spec compliance review (objective: matches requirements exactly, nothing more/less).
  2) Code quality review (objective: maintainability, cleanliness, tests, patterns).
- Do not start code quality review until spec compliance is approved.
- If a reviewer finds issues, loop fixes and re-review until approved.

## Execution Discipline

- Extract all tasks before implementation begins.
- Dispatch a fresh worker subagent for each independent task (no context pollution).
- No parallelization of implementers. Complete a task (incl. both reviews) before starting the next.
- Answer clarifying questions before implementation starts, especially where the plan is ambiguous.
  - Example: Task T3 requires explicit confirmation of the default base branch; confirm before work.

## Testing and Tooling Guidelines

- Python: Version 3.11, tests via pytest. Avoid external dependencies unless explicitly required.
- Bash: POSIX-compatible; include `#!/usr/bin/env bash` and `set -euo pipefail` in scripts.
- Tests for bash may be simple shell scripts that assert expected output using greps and return
  non-zero on mismatch. Bats is not required.

## Documentation and Style

- Keep READMEs concise and practical with real examples.
- Limit markdown lines to <= 100 characters where feasible.
- Favor clarity over cleverness. Use explicit names and small functions.
- Avoid over-engineering; implement only what is requested by the plan.

## Acceptance Review Aids

- Acceptance criteria are enumerated in the plan for each task. Reviewers should reference them
  directly when verifying spec compliance.
- For spec reviews, rely on code inspection and explicit comparison to the plan (method: code-inspection).
- For code quality reviews, assess maintainability, testing approach, naming, and adherence to repo
  policies (branch hygiene, no protected branches, simple dependencies).

## Ambiguities and Defaults

- Unless otherwise specified, the default base branch is develop.
- If any task text contains [TBD] or requires confirmation (e.g., default base branch in T3),
  the implementer must ask and receive explicit confirmation before starting.

## Ready-to-Merge Definition

- All tasks completed with passing spec and code quality reviews.
- Final reviewer confirms all requirements were met and the work is ready to merge into the base
  branch via the standard finishing process.