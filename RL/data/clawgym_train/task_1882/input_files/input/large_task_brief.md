Main Agent Supervisor — Phase 1 MVP

Objective
- Stand up a practical supervisor layer that defaults to execution, suppresses permission loops, and escalates only for true approvals or real blockers.

Scope (Phase 1)
- Policy brain: classifier (AUTO/CONFIRM/ESCALATE), pre-send gate, triage/watchdog states.
- Coaching fields in outputs (assumptions, defaults_used, recommended_next_action).
- Lightweight task-state file at .tasks/supervisor-demo.md.
- Run policy on a set of sample drafts to validate behavior.

Context & Constraints
- No verified pre-send hook yet; enforcement is prompt/policy-driven.
- Keep user-visible interruptions to a minimum; focus on internal, reversible actions by default.
- External sends and destructive actions require confirmation.

Milestones
- Draft policy and references (DONE).
- Prepare sample drafts for evaluation (DONE).
- Implement decision writer to output/decisions.jsonl and rewrite.md (IN PROGRESS).
- Create and maintain the checkpoint file (.tasks/supervisor-demo.md) (IN PROGRESS).
- Optional watchdog via cron (DEFERRED to Phase 2).

Current Notes
- Sample drafts cover: internal doc work (AUTO), external email (CONFIRM), destructive cleanup (CONFIRM), blocked staging deploy (ESCALATE), design variants (AUTO).
- Need crisp, one-question escalation formats for CONFIRM/ESCALATE cases.
- Ensure rewritten AUTO messages state assumptions/defaults and proceed without asking.

Known Blockers
- Missing pre-send interception hook for hard enforcement; rely on policy output for now.
- Staging deploy requires a valid API key; cannot test end-to-end escalation loop without it.

Desired Next Steps
- Apply the policy to the drafts and generate output/decisions.jsonl and output/rewrite.md.
- Create output/.tasks/supervisor-demo.md with clear status, completed steps, blocker, and next action.
- Verify that AUTO rewrites contain no questions and note the chosen defaults.