# Q2 Onboarding Revamp — Initiative Brief

Overview
Q2 focus: overhaul the end‑to‑end new‑hire onboarding experience to reduce time‑to‑productivity, standardize across departments, and measurably improve early‑tenure engagement. The work will align documentation, communications, portals, and metrics under a single source of truth and lightweight automation.

Objectives (by June 30, end of Q2)
- Reduce engineering “time to first meaningful PR” from 14 days median to 7 days (50% reduction).
- Reduce Sales “time to first qualified call” from 12 business days to 8 days (33% reduction).
- Improve new‑hire 30‑day satisfaction by +20 points (baseline 58 → target 78) on 0–100 scale.
- Standardize onboarding checklists (company‑wide and role‑specific) with 90% manager adoption.
- Instrument 30/60/90‑day surveys and create a durable, self‑serve KPI dashboard.

Scope (in scope)
- Audit and clean up docs in /workspace/docs/onboarding and /workspace/docs/checklists.
- Redesign welcome email sequence and template library (Mailgun) in /workspace/templates/email/onboarding.
- Build a Day 1 portal (static site served from /workspace/repos/hr-tools/onboarding-portal) linking to systems (Okta, Slack, Google Workspace) and core resources.
- Create role‑specific tracks for Engineering, Sales, and Support (curricula, checklists, required readings).
- Automate Slack welcomes and buddy pairing (via /workspace/scripts/slack_inviter.py and #onboarding-buddies).
- Add metrics and survey instrumentation (Typeform + CSV export at /workspace/analytics/onboarding-metrics.csv).

Out of Scope (Q2 only)
- Compensation/benefits policy changes.
- Recruiting pipeline or ATS changes.
- Company rebrand or tone‑of‑voice overhaul beyond minor copy edits for clarity.

Success Criteria & Measurement
- Leading indicators: checklist completion rates (company and role tracks), portal usage analytics (unique visitors, bounce), email open/click rates per step.
- Lagging indicators: time‑to‑first‑PR (Eng), time‑to‑first‑qualified‑call (Sales), 30/60/90‑day satisfaction (Typeform), buddy program participation.
- A single dashboard refreshed weekly from onboarding-metrics.csv and Typeform exports.

Deliverables (mapped)
- Comprehensive asset inventory + gap map.
- New welcome email templates (3–5 messages with tested subjects and CTAs).
- Day 1 portal MVP + manager checklist.
- Role‑specific onboarding tracks v1 for Eng, Sales, Support.
- Metrics and survey instrumentation with a documented data flow and a JSON/CSV schema.

Timeline & Milestones
- Apr 1–12: Audit + gap analysis; define target architecture and IA.
- Apr 15–May 10: Email sequence redesign; Day 1 portal MVP; checklist drafts.
- May 13–31: Role tracks v1; automation scripts; pilot with May cohort.
- Jun 1–21: Instrumentation; dashboard; revisions from pilot; rollout plan.
- Jun 24–30: Final QA, documentation, and handoff.

Stakeholders
- Initiative owner: Jordan (People Ops).
- Engineering lead: Alex (Eng).
- Design/content: Priya (Design).
- L&D/enablement: Taylor (L&D).
- Data/metrics: Sam (Data).

Tools & Systems
- Docs: Markdown in /workspace/docs/, synced to Notion (People Ops is source of truth).
- Automation: Python scripts in /workspace/scripts/, Slack API, Mailgun.
- Repos: /workspace/repos/hr-tools for portal and utilities.
- Surveys: Typeform; data exported to /workspace/analytics.
- Communication: Slack (#onboarding, #onboarding-buddies).

Risks & Mitigations
- Access to systems (Okta, Mailgun) may lag → pre‑request credentials in week 1.
- Fragmented ownership → weekly standups and a single parent task with child tasks per stream.
- Scope creep → enforce out‑of‑scope list and phase multi‑team asks to Q3.

Dependencies
- IT for Okta provisioning; Security review for portal; Legal for handbook excerpts approvals.

---

This brief governs the “Q2 Onboarding Revamp” parent task and all child tasks (audit, email sequence, Day 1 portal/checklist, role tracks, metrics/surveys).