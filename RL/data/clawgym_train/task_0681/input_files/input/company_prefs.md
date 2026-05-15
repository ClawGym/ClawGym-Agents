Company & Assistant Profile (current hot memory)

Identity
- Assistant codename: Reef
- Role: pragmatic assistant for engineering + ops with a focus on truthful retrieval
- Audience preferences: concise, actionable bullets over long prose

Standing preferences
- Prefer bullet lists and concrete next steps
- Default to short, specific examples over abstract theory
- For code reviews, focus on correctness first, performance second

Code review checklist (duplicated here; originally from topic docs)
- Verify tests added or updated
- Check error handling and edge cases
- Confirm logging levels are appropriate
- Ensure docs/comments updated
- Confirm no secrets or credentials in code
- Verify performance regressions are unlikely

Current priorities (too detailed for hot canon)
- Complete Apollo migration step 3 (data copy dry-run) by 2026-04-22
- Draft layered memory pilot for support workflows
- Reduce vector queries from 50 to 15 per answer

Live status snapshots (should not be in hot memory)
- 2026-04-18 10:15 — Queue: 7 tasks, Errors: 2, Alerts: red
- 2026-04-17 17:00 — Daily dashboard digest attached below
  • “Open incidents: 0, Disk free: 8%, Model timeout alerts: 3”
- 2026-04-16 09:00 — Qdrant health: “OK (but slow)”

Outdated or volatile facts (risk of fossilization)
- Disk free: 8% (from 2026-04-17; not a durable truth)
- “Always prefer project docs over doctrine” — NOTE: This contradicts our intent and may be a transient workaround from last week.

Cross-project lessons (candidate material, but too wordy for hot canon)
- Logs and dashboards are derived state; they should be summarized and never treated as durable truth.
- Keep hot canon small: if everything is hot, nothing is.
- Retrieval should start from hot canon and an index that selects only relevant topics.

Notes to self (should live in daily logs instead)
- Today: investigate flaky link-checker CI (may be related to caching config).
- Ping ops about rotating the Qdrant index tonight.

Attachment (improperly pasted into hot memory)
- Daily dashboard digest JSON from 2026-04-17 (removed here for brevity in this copy).