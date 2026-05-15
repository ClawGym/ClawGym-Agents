# 6-Month Product Strategy Draft (FY26 H1)

Owner: Product Team
Last updated: 2026-04-12

## Context and Baseline (last 8-week average)
- DAU: ~13.5k (rising to 14.8k in the latest week)
- Signup conversion: ~4.3% (latest: 4.6%)
- Activation (new users completing first value moment): ~45% (latest: 48%)
- Weekly churn: ~1.5% (latest: 1.4%)
- NPS trending upward from 22 → 29

Interviews indicate friction in onboarding (especially early setup), growing demand for collaboration and integrations (SSO, Jira/Slack), and sensitivity to performance during peak hours.

## Goals (by end of 6 months)
1) Increase activation from ~45% to ≥55%.
2) Raise signup conversion from ~4.3% to ≥5.5%.
3) Reduce weekly churn from ~1.5% to ≤1.2% (relative –20%).
4) Grow DAU by ≥20% (from ~13.5k to ≥16.2k).
5) Establish enterprise readiness signals (SSO, audit logs) and ship share/comment for team workflows.

## Strategic Bets
- Onboarding Revamp: Reduce friction and time-to-value with guided setup, templates, and contextual hints.
- Collaboration: Enable shareable links, comments/mentions, and basic presence to encourage team adoption and retention.
- Integrations & Reporting: Ship SSO and Jira/Slack integrations; expand reporting that shows value delivered and adoption.
- Pricing & Packaging: Introduce usage-based tiers with clearer entitlements to align value with cost and reduce churn risk.

## Initiatives and Success Metrics
1) Onboarding Revamp (Months 1–2)
   - Approach: Interactive checklist, starter templates by role, inline help, and default demo data path.
   - Success metrics: Activation +8 pts; signup-to-activated cycle time –25%; fewer support tickets on setup.
   - Dependencies: Design bandwidth; analytics instrumentation for funnel steps; localization later.
   - Risks: Scope creep; mitigate via MVP and phased rollout.

2) Collaboration Beta (Months 2–4)
   - Features: Shareable links with granular permissions, inline comments/mentions, lightweight presence.
   - Success metrics: ≥30% of active accounts share at least one item/week; +3 pts retention; ↑avg session length.
   - Constraints: p95 latency target <300ms for comment operations; access control review.

3) Integrations & Reporting (Months 3–6)
   - Integrations: SSO (SAML/OIDC), Jira issue sync, Slack notifications.
   - Reporting: Adoption dashboards (cohorts, feature usage), export.
   - Success metrics: ≥35% of orgs connect ≥1 integration; NPS +3; fewer “missing visibility” churn reasons.
   - Risks: Security/compliance review lead times; API limits; mitigate via staged pilots and API backoff.

4) Pricing & Packaging (Months 4–6)
   - Approach: Usage-based tiers with guardrails; clearer upgrade paths; annual plans for enterprise.
   - Success metrics: ARPPU +10%; reduced downgrade-related churn; improved win rate in mid-market.
   - Dependencies: Billing provider capabilities; legal review for enterprise terms.

## Architecture and Technical Considerations
- Performance & Reliability: Maintain p95 API <300ms and 99.9% availability; isolate collaboration writes with queue-based buffering; selective caching for read-heavy endpoints.
- Data & Analytics: Expand funnel step tracking (especially early setup), event schema versioning, and reporting ETL pipelines; define SLAs for data freshness (<2h lag).
- Security & Compliance: SSO, audit logs, role-based permissions; secure defaults for sharing; periodic security reviews.
- Platform Debt: Pay down onboarding code complexity via modularization; introduce contract tests for integrations; observe error budgets.

## Timeline and Milestones
- Month 1: Instrument onboarding funnel; ship inline hints to early-access; performance footprint analysis for collaboration.
- Month 2: Onboarding Revamp MVP GA; begin comment service behind feature flag.
- Month 3: Collaboration Beta (comments, sharing) to 20% of orgs; Slack notification integration pilot.
- Month 4: Collaboration GA; Jira integration beta; begin SSO enterprise pilot; start pricing experiments.
- Month 5: SSO GA; reporting dashboards v1; pricing tiers finalized.
- Month 6: Pricing rollout; reporting v2 with exports; scale integrations; verify goal attainment.

## Risks and Mitigations
- Adoption risk if onboarding scope expands → Keep MVP strict, A/B test each step.
- Data quality risk in funnel metrics → Schema governance, backfills, and automated validation.
- Performance under collaboration load → Backpressure, rate limits, and read replicas.
- Enterprise security blockers → Early review cycles and clear documentation.

## Measurement Plan
- Weekly review of: conversion %, activation %, DAU, churn %, NPS, session length.
- Cohort and funnel diagnostics for onboarding steps; report impact of changes within 2 weeks of each release.
- Tie experiments to clear “ship-to-impact” timelines with guardrail metrics (latency, error rate).

---

This is a draft; finalize resourcing and risk budgets after design estimates and security review.