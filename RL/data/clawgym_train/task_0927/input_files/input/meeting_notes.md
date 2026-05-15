# Stakeholder Sync — Summary Notes
Date: 2026-04-17
Attendees: CEO (Lena), Sales (Marco), Product (Sarah), Eng (Priya, Leo), QA (Nina), Marketing (Ivy)

## Decisions
- Commit to Acme design partner demo on 2026-05-08 13:00–14:00. Demo must show Slack notifications and guided onboarding.
- Slack integration MVP must be available to design partners by 2026-05-10 (OBJ2/KR1).
- Onboarding Checklist v1 must ship before Marketing campaign lands (target 2026-05-12) (OBJ1/KR2).
- If trade-offs are required this week, prioritize demo readiness and integration deliverables over non-critical refactors.

## Constraints
- Security review is scheduled for 2026-05-08 11:00–12:00; any integration endpoints must pass the basic checklist.
- Architecture Council: Priya blocked 2026-05-06 14:00–16:00.
- Leo PTO on 2026-05-08 15:00–17:00 (afternoon).
- UX research sessions booked 2026-05-11 14:00–16:00 (Sarah).
- Avoid major backend schema changes this week to reduce demo risk.
- Marketing launch comms for onboarding begin 2026-05-13; slipping onboarding past 2026-05-12 undermines OBJ1/KR2.

## Dependencies (Backlog IDs)
- T-140 “Pilot Demo Script & Dataset (Acme)” depends on:
  - T-131 “Slack Integration MVP (incoming webhooks + OAuth)”
  - T-120 “Onboarding Checklist v1”
- T-120 depends on T-150 “Analytics Events Coverage (Activation funnel)” for instrumentation.
- T-131 depends on T-135 “Webhook Rate Limit Fix”; optional hardening T-180 “Retry & Backoff for Slack webhook deliveries” can follow MVP if time permits.

## Acceptance Criteria Highlights
- Slack MVP: OAuth connect + inbound webhook to send basic event to Slack channel; evidence via live demo.
- Onboarding Checklist v1: 6–8 steps with progress, clear “next step,” tracked via analytics events.
- Demo: Tailored to Acme’s data (sample dataset), clear narrative of problem → solution → value.

## Risks Called Out
- OAuth/Slack app review delays could block MVP exposure; consider internal distribution for demo.
- Analytics gaps could make activation improvements hard to measure.
- Rate limit bugs may surface under demo conditions; ensure a safe path and backoff.

## Resourcing & Ownership
- Priya (backend): T-131, T-135, T-180
- Leo (frontend): T-120, T-150 (implementation support)
- Nina (QA/Analytics validation): T-150 validation + smoke tests
- Sarah (PM/Content): T-140 demo script/dataset, stakeholder coordination

## This Week Focus Window
Plan for the week of 2026-05-05 to 2026-05-11.
Primary push: de-risk Slack MVP (by 05-10), deliver compelling Acme demo (05-08), and lock Onboarding Checklist v1 (by 05-12).

## Notes
- If Slack app store timing is uncertain, use “Distribution: Internal Only” for the demo.
- Keep 15–30 minute buffers between blocks for context switching.
- Document assumptions and call out any slips immediately.