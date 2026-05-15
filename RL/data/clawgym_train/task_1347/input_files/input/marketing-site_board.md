# marketing-site Kanban Board

## Meta
project_id: marketing-site
board_version: 1.0
updated: 2026-04-18 15:45
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
| KB-099 | Prepare April blog topics | backlog | P3 | content | 2026-04-28 | - | 2026-04-16 |
| KB-101 | Homepage hero redesign | ready | P1 | frontend | 2026-04-24 | - | 2026-04-18 |
| KB-115 | Contact form tracking | in-progress | P2 | frontend | - | - | 2026-04-17 |
| KB-118 | Cookie banner localization | blocked | P1 | frontend | - | Legal review | 2026-04-18 |
| KB-120 | SEO audit fixes | review | P1 | seo | 2026-04-16 | - | 2026-04-18 |

## WIP Limits
- in-progress: 2
- review: 4

## Rules Snapshot
- Use `marketing-site_rules.md` for state mapping and acceptance policies.

## Notes
- “Done” requires evidence: QA checklist + artifact links (e.g., PR, staging URL).
- KB-120 acceptance criteria are not documented in the card; confirm before closing.