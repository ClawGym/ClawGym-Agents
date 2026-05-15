# Decision Prompts for DevGraph (Beta Go-To-Market)

Use the brief to think through the following decisions. Assume we are finalizing our beta GTM for DevGraph in the next 2 weeks.

1) Deployment Strategy at Launch
- Decide whether we should ship beta as SaaS-only (US region) or pull in a limited “private region” (EU) or VPC install for a small set of prospects.
- Constraints: SOC 2 Type I today; Type II Jan 2027 target. EU region possible by Sep 2026; VPC install earliest H2 2026 prototype.
- What breaks if we say “SaaS-only for beta” for mid-market fintech? Who do we disqualify and is that acceptable?

2) Packaging and Pricing for Beta
- Choose between Seat-based, Service-based, or Hybrid for beta. Propose an initial tier structure and price anchors consistent with signals in the brief.
- Requirements: SSO on paid tiers; min commit that supports 40–100 services pilot; keep LLM cost exposure manageable.
- State top risks of the chosen model and how we mitigate them in the first 3 months.

3) Launch Motion and Channels
- Pick a primary motion for the first 90 days: Top-down, Bottom-up, or Dual. Define why this fits DevGraph now.
- Identify the top two channels we should invest in before KubeCon NA (Oct 2026) and the proof we expect from them.

4) Pilot Design and Success Criteria
- Tighten the 4–6 week pilot into a 30-day “minimum viable pilot” that still demonstrates value. Specify scope, integrations, and concrete exit criteria that a Head of Platform will respect.
- Include a plan for ingestion data quality and a fallback if ownership mapping is incomplete in week 1.

5) Competitive Positioning and Messaging
- Position DevGraph against Atlassian Compass, Cortex, and Backstage in one crisp angle we can defend.
- Choose one tagline and one sentence we can put on the beta landing page that will resonate with SRE/Platform leads.

6) Risks, Unknowns, and Early Warning
- Name the top two unknowns that could sink the beta GTM and define early warning signals (leading indicators) to monitor in the first 60 days.
- If we miss EU data residency for one prospect that insists on it, what is our fallback narrative that preserves the relationship without overcommitting?

Notes:
- Keep the tone direct; say “unknown” where we truly don’t know.
- Ground all trade-offs in the specifics of DevGraph’s capabilities, security posture, and design partner feedback.
- Prefer decisions we can test within 90 days over hypotheticals we can’t validate this year.