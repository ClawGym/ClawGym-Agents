# api-core Kanban Board

## Meta
project_id: api-core
board_version: 1.0
updated: 2026-04-18 16:30
lane_model: basic

## Lanes
- backlog
- ready
- in-progress
- blocked
- review
- done

## Cards
| id | title | state | priority | owner | due | depends_on | updated |
|----|-------|-------|----------|-------|-----|------------|---------|
| KB-001 | Define API scope | backlog | P2 | backend | - | - | 2026-04-15 |
| KB-002 | Add OAuth2 support | ready | P1 | backend | 2026-04-25 | - | 2026-04-18 |
| KB-003 | Fix flaky tests in CI | blocked | P0 | qa | - | KB-002 | 2026-04-18 |
| KB-010 | Refactor request handlers | in-progress | P2 | backend | - | - | 2026-04-17 |

## WIP Limits
- in-progress: 3
- review: 5

## Rules Snapshot
- Use `api-core_rules.md` as source of truth for state mapping and policies.

## Notes
- CI failures linked to OAuth2 mock tokens.
- Keep IDs in KB-<number> format and never reuse.