# Heartbeat Rules

These rules define when to run self-reflection, what to record, and how to update the memory system.

## Triggers
- After completing any important task or work session
- At least once per day (daily check before end-of-day UTC)
- On explicit user request for self-reflection
- When any error, inconsistency, or correction is discovered
- When a significant new pattern, preference, or rule is identified

## Execution Flow
1. Start heartbeat and note the start time.
2. Review changes since the last heartbeat (tasks completed, errors found, new patterns).
3. Update memory.md:
   - Add or revise items under Preferences, Patterns, and Rules.
4. Record corrections in corrections.md:
   - One row per error with Date, What I Got Wrong, Correct Answer, and Status.
5. Update index.md:
   - Recompute line counts and set Last Updated for modified files.
6. Update heartbeat-state.md:
   - Set last_heartbeat_started_at and last_reviewed_change_at with current ISO 8601 timestamps.
   - Set last_heartbeat_result to HEARTBEAT_OK if no changes, or HEARTBEAT_UPDATED if memory or corrections were modified.
7. If large files or deprecated entries accumulate, move old snapshots or notes to archive/.

## Recording Obligations
- Always use ISO 8601 timestamps (YYYY-MM-DDTHH:mm:ssZ) for state updates.
- Always log discovered errors in corrections.md with Status set to Logged or Updated.
- Keep memory.md concise and actionable; prefer bullet points.
- Avoid absolute paths; use workspace-relative paths in all references.

## Status Values
- PENDING: Heartbeat scheduled but not executed
- HEARTBEAT_OK: No significant changes since last review
- HEARTBEAT_UPDATED: Memory or corrections updated during this heartbeat
- HEARTBEAT_ERROR: A problem occurred during the heartbeat

## Timestamp Guidance
- Use UTC for all timestamps.
- Format must be ISO 8601 with trailing Z, for example: 2026-04-20T12:34:56Z

## Notes
- If a trigger fires but no material changes are found, still update heartbeat-state.md and return HEARTBEAT_OK.
- Prefer smaller, frequent updates over large, infrequent ones.