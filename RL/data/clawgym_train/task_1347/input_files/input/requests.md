# Requested Kanban Updates

This request spans two projects and must keep boards isolated. Initialize workspace-local boards from the provided files and apply deterministic processing rules with WIP enforcement.

## 1) Setup
- Create workspace-local boards for:
  - api-core (initialize from input/api-core_board.md and input/api-core_rules.md)
  - marketing-site (initialize from input/marketing-site_board.md and input/marketing-site_rules.md)
- If any required sections are missing, repair non-destructively and log the repair.
- Required sections: Meta, Lanes, Cards table, WIP Limits.
- Deterministic processing and WIP limits must be enforced.

## 2) api-core updates
- Move KB-002 from ready to in-progress.
- Leave KB-003 in blocked (do not move it).
- Add one new backlog card titled "Implement rate limiter" with priority P1, owner "backend", assign a new unique KB-<number> ID.
- Enforce WIP limits for in-progress; do not exceed the limit.
- For every change, append a log row with timestamp and a one-sentence rationale prefixed with "rationale:".

## 3) marketing-site updates
- Move KB-101 from ready to in-progress.
- Move KB-120 from review to done only if acceptance criteria are met; include completion evidence in the log note.
- If acceptance criteria are unclear, add a blocker note instead of moving to done.
- Add one new backlog card titled "Launch checklist" with priority P0, owner "pm", due today, with a new unique KB-<number> ID.
- Enforce WIP limits for in-progress; do not exceed the limit.
- For every change, append a log row with timestamp and a one-sentence rationale prefixed with "rationale:".

## 4) Export artifacts
Export the updated artifacts to:
- output/kanban/index.md (registry listing both projects using relative paths)
- output/kanban/api-core/board.md
- output/kanban/api-core/rules.md
- output/kanban/api-core/log.md
- output/kanban/marketing-site/board.md
- output/kanban/marketing-site/rules.md
- output/kanban/marketing-site/log.md

## Index requirements
- Include a machine-readable Projects table with fields:
  project_id, aliases, workspace_root, board_mode, board_path, rules_path, log_path, last_used.
- Use board_mode=workspace-local and relative paths pointing to the exported output/ locations.
- Update last_used to today’s date for both projects.

## Board and Log requirements
- Boards must keep required sections (Meta, Lanes, Cards table, WIP Limits) and preserve existing lanes.
- Update card states and set updated dates to today where changed.
- Enforce KB-<number> ID format for all cards.
- Each log.md must keep the table header and include entries for each change with:
  timestamp, action, card_id, from_state, to_state, actor, and a rationale note.
- Any move to done must include completion evidence text in the note.