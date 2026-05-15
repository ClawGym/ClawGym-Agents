# Core Platform — Working Notes (Week of Apr 19, 2026)

## Milestones & Risks
- Gateway stability: Rate-limit policy update pending review today.
  - Owner: Sara (Core)
  - Risk: Without this, alert noise persists; incident action items blocked.
- Orders DB migration dry-run scheduled 2026-04-20 16:00–17:30.
  - Owner: Miguel (Core) + Derek (Data Eng)
  - Prep: Rollback procedure walkthrough; ensure monitoring dashboards are ready.
- SSO renewal with AuthLion — renewal review 2026-04-20 10:00.
  - Owner: Jenna (Security)
  - Risk: Contract renews this month; need DPA confirmation and scope alignment.
- Q2 Core Platform Milestone Checkpoint on 2026-04-21 14:00.
  - Owner: You
  - Prep: Delivery confidence across Gateway stability, SSO renewal, DB migration.

## Cross-team Dependencies
- Payments team blocked on gateway schema change from Data Eng.
  - Ask: Confirm schema and coordinate deployment window today.
  - Owner: Alex (Core) to sync with Derek (Data Eng).
- SRE needs Core approval on API Gateway config for alert tuning before incident review.
  - Owner: You or Alex (Core) to approve by 10:00.

## Admin / Finance
- CloudScale April invoice flagged overdue by billing email this morning.
  - Owner: You to coordinate with Finance; avoid service interruption.

## To-Do (Personal)
- Review Sara’s rate-limit PR (today).
- Draft 3-slide update for VP staff checkpoint (by 2026-04-21).
- Skim AuthLion security questionnaire; confirm renewal scope with Jenna (by 2026-04-20 EOD).