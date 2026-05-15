Risk Tolerance
- Data integrity and access control: very low tolerance for defects (prefer brief delays over rework or incidents)
- UX polish and copy: moderate tolerance (acceptable to refine post-pilot if not misleading)
- Schedule: 8 weeks target; minor slips acceptable at irreversible points to avoid high-blast-radius mistakes
- Visibility: Keep critique quiet and outcome-focused; avoid ceremony

Critique Depth Preferences (choose lightest that catches likely failure)
- Before branching (e.g., decomposing architecture into tasks): Depth = standard (30–60s)
- Before commitment/irreversible edits (e.g., schema migration, SSO config, PII policy, production flags): Depth = deep (stress test, short but decisive)
- After surprising evidence (contradictory pilot data, tool outputs): Depth = standard
- After user friction (repeated revisions, support tickets on same step): Depth = standard with a small plan rewrite if framing was wrong
- At risky handoffs (to ops/support or external partners): Depth = standard

Phase-Level Nuance
- P2 Architecture & Data Model: standard by default; deep specifically at data model freeze and identity boundary ADRs
- P4 Integrations: deep for SSO/SCIM approach and billing idempotency; standard for CRM field mapping unless it contradicts data model
- P5 Data Migration & Tenant Seeding: deep for prod-bound migration plan and rollback; standard for dry run checklists
- P6 Security/Compliance: deep for PII retention and role escalation controls; standard for dashboard scope
- P7 Pilot: light for routine UX tweaks; standard when evidence contradicts earlier assumptions
- P8 Launch/Handoff: standard at runbook/handoff; deep at irreversible launch toggles affecting data paths

Trigger Signals We Care About
- Multi-domain identity requirements or unusual IdP constraints
- Normalization risks (free-text fields feeding rules, e.g., company_size)
- Missing idempotency in webhook/event flows
- Ambiguous field labels controlling roles/permissions
- Accessibility regressions in shared components
- Email deliverability assumptions (SPF/DKIM/DMARC not verified)

Anti-Noise Rules
- Keep the breakpoint questions to 1–2 focused prompts
- Do not log minor typos or one-off slip-ups without a reusable lesson
- If critique changes the frame, rewrite the plan immediately rather than patching later

Ownership and Behavior
- PM ensures checkpoint is observed at phase boundaries
- Tech Lead chooses depth per constraints above; err on standard for branching, deep for irreversible
- Designers run a quick a11y pass at component freeze
- Write the smallest reusable lesson to memory; avoid narrative reports