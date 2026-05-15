Addendum — 2026-04-10 (post-demo) and late-Thursday clarifications

Thursday 2026-04-09 — Afternoon updates
16:22 Me → Legal Sam: On KiteMetrics – your data residency addendum is accepted. I’m proceeding to sign the 3-month contract today so we can enable dashboards by Monday.
16:28 Sam: Okay. Noting contract term minimum is 3 months per vendor policy.
16:35 Me → Jenna: I rejected the idea to postpone the public roadmap to next week. We’ll publish today as planned; keeping momentum matters.
16:42 Me → Security channel: OTel tracing is too expensive at full rate right now. I decided to cap sampling at 10% for this week to keep infra costs predictable before quarter planning.

Friday 2026-04-10 — Post-demo decisions
16:12 Me → Tara: For the public roadmap, I decided to include only near-term items (onboarding, analytics, auth migration). I’m excluding SSO and deeper platform work to avoid overpromising externally.
16:18 Me → Jenna: Setting an explicit onboarding KPI target: 30% completion of the new flow by end of April. This is a public commitment in the roadmap notes.
16:24 Jenna: Got it. That’s ambitious. We’ll track weekly.
16:40 Me → Bob: The ADR for auth will be written Monday, but I’m keeping the token switch quiet in external comms unless someone asks. Internally, we proceed with token rollout plan next sprint.
16:47 Me → Luis: I rejected refactoring the chart library this weekend. SparklineJS stays for MVP; we’ll revisit next sprint.
16:55 Me → Team: SSO is officially deferred to next sprint; no hidden work this week. Close all SSO tasks as “deferred”.

Context of these addendum decisions:
- KiteMetrics contract signing after Legal addendum (vendor commitment is hard to undo mid-term)
- Roadmap publication timing reaffirmed under Sales pressure to move it
- Telemetry sampling reduced for cost control pre-budget adjustments
- Scope of public roadmap intentionally constrained to avoid external commitments beyond confidence level
- Onboarding KPI set and publicly noted (harder to reverse once announced)
- Communication choice to downplay auth switch in investor/demo narratives
- Technical deferral choices (keep SparklineJS; SSO deferred) to preserve focus and avoid scope creep