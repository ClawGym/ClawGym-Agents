# Q2 Onboarding Revamp — Context & Decisions

Use this file as the operational context for all task notes and implementation work. It records settled decisions, standards, and the key file paths needed to resume after a pause.

Decisions (settled)
- Source of truth: People Ops maintains canonical onboarding content in Notion; engineering and design work from Markdown in /workspace/docs/onboarding and /workspace/docs/checklists. A simple sync script copies approved Markdown to Notion weekly (manual for now).
- Email platform: Mailgun will send the welcome sequence. Templates live in /workspace/templates/email/onboarding and are versioned via Git. Use JSON frontmatter for subject, preview, and UTM params; keep HTML partials in /workspace/templates/email/partials.
- Day 1 portal: Static site (no auth) generated from /workspace/repos/hr-tools/onboarding-portal with Netlify‑style deploy previews. Link out to Okta, Google Workspace, Slack, and core docs; do not embed secrets. Security review required before production.
- Slack automation: Use /workspace/scripts/slack_inviter.py with a bot token restricted to #onboarding and #onboarding-buddies. Buddy assignments are stored in /workspace/analytics/buddy-assignments.csv and posted automatically.
- Measurement: 30/60/90‑day Typeform surveys (export CSV weekly). Aggregate metrics into /workspace/analytics/onboarding-metrics.csv with columns: date, cohort, department, metric, value, source.
- Style & tone: Clear, friendly, contemporary; no rebrand this quarter. Follow /workspace/docs/style-guide.md. Write at a 9th‑grade readability level; use action‑oriented headings.
- File conventions: kebab-case for filenames; Markdown with H1 as title; frontmatter optional for docs, required for email templates. Checklists stored in /workspace/docs/checklists with “- [ ]” items.

Key Workspace Paths
- /workspace/docs/onboarding/ — core onboarding docs (overview, policies, FAQs).
- /workspace/docs/checklists/ — manager and role checklists (Markdown).
- /workspace/templates/email/onboarding/ — Mailgun email templates (HTML + JSON frontmatter).
- /workspace/templates/email/partials/ — shared HTML partials (headers, footers, buttons).
- /workspace/repos/hr-tools/onboarding-portal/ — Day 1 portal code and content.
- /workspace/scripts/slack_inviter.py — Slack automation script (welcomes, buddies).
- /workspace/analytics/onboarding-metrics.csv — metrics sink for dashboard.
- /workspace/analytics/buddy-assignments.csv — source for buddy pairing automation.
- /workspace/docs/style-guide.md — content and voice guidelines.

References & Access
- Slack channels: #onboarding (announcements), #onboarding-buddies (pairs).
- Systems: Okta (account provisioning), Google Workspace (calendars, Docs), Mailgun (transactional email).
- Surveys: Typeform forms titled “New Hire 30”, “New Hire 60”, “New Hire 90” owned by People Ops.

Constraints & Risks
- Do not alter compensation or benefits content; link to HR handbook excerpts approved by Legal.
- Security review required for any new public endpoints (including the Day 1 portal).
- Mailgun sending domain is verified; use company.org domain and UTM “onboarding_q2”.

Operational Notes
- Pilot cohort: May new hires (Eng + Sales + Support). Collect qualitative feedback in week 3 via a quick Slack thread and add summaries to /workspace/analytics/notes/pilot-feedback.md.
- Weekly cadence: Monday standup, Thursday async status update in #onboarding with links to updated docs and PRs.

Sources
- This context supports outputs that will explicitly cite:
  - input/brief.md — initiative goals and scope
  - input/context.md — this context file with decisions and paths

Use the above to craft concrete, checkable steps in each task note and to ensure all “## Context” sections list the relevant paths so anyone can resume work mid‑stream.