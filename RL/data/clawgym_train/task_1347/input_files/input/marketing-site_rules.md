# marketing-site Kanban Rules

## State Mapping
| lane_label | canonical_state |
|------------|-----------------|
| backlog | backlog |
| ready | ready |
| in-progress | in-progress |
| blocked | blocked |
| review | review |
| done | done |

## Prioritization
1. Resolve blockers with highest downstream impact
2. Ready cards by priority (P0 > P1 > P2 > P3)
3. Due date proximity
4. Oldest first

## Policies
- Card IDs must be KB-<number> and unique.
- In-progress WIP limit is 2; do not exceed.
- Moves to done require completion evidence in the log note (e.g., “evidence: PR #234 merged, QA checklist attached, staging URL verified”).
- If acceptance criteria are unclear, do not move to done; mark the card as blocked with a clear blocker note.
- Preserve board isolation; do not move cards across projects.

## Notes
- Marketing approves final copy and design before “done”.
- KB-120 currently lacks explicit acceptance criteria; verify with SEO owner before closing.