# api-core Kanban Rules

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
1. blocked dependency with highest downstream impact
2. ready cards with P0/P1
3. due-date pressure
4. age in queue

## Policies
- Card IDs follow KB-<number> format and are never reused.
- Enforce WIP limits strictly (in-progress WIP = 3).
- Do not move blocked cards unless blocker is resolved and evidence is logged.
- Any move to done must include completion evidence in the project log.
- Each card should include: id, title, state, priority, owner, updated.

## Notes
- KB-003 depends on OAuth2 flows (KB-002), keep it in blocked until the dependency is resolved.
- Use deterministic ordering and never skip blockers.