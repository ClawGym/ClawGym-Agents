Company and product
- AcmeFlow is a B2B workflow automation SaaS used by product, operations, and engineering teams to orchestrate recurring tasks and integrations.
- Current monetization is seat-based with tiered feature gates (Basic, Pro, Enterprise). There are no metered overages today; heavy users drive higher variable costs without corresponding revenue.

Customer and contract mix
- Revenue mix: ~55% enterprise, ~35% mid-market, ~10% SMB.
- Billing mix: ~62% annual, ~20% quarterly, ~18% monthly.
- Typical buyer concerns: budget predictability, fair alignment to realized value, and procurement’s preference for clean, auditable invoices.

Sales and finance posture
- Sales velocity targets: keep win rate and sales cycle within ±10% of current baselines during any pricing changes.
- Finance mandate: keep gross margin ≥78% and maintain positive NRR momentum.
- Discounting is actively used in competitive deals; controlling discounting under any new model is a concern.

Utilization and usage insights
- Median seat utilization is ~62% (many accounts purchase buffer seats that remain underused).
- Value delivery correlates with “automations run” and “API calls” executed; top 10% of customers account for ~56% of total runs (heavy-tail distribution).
- Support and infrastructure costs correlate with usage volume; variable cost per 1,000 runs is estimated at ~$3.75 (infrastructure ~$2.10 + support ~$1.65).

Operational readiness and limits
- Metering data is available for automations run and API calls with ~15-minute latency; estimated data accuracy ~98%.
- Current billing system supports plan-level meters and feature flags; cannot do mid-cycle meter/proration changes until November 2026 (Q4).
- Legal/commercial requires 60-day advance notice for material pricing changes on existing contracts; migrations should align with renewal where possible.

Seasonality and planning window
- Q3 usage seasonality is mild (+~6% vs Q2), which reduces the risk of confusing spikes during pilot.
- Proposed Q3 2026 milestones:
  - July: closed beta with ~20 opt-in accounts (no proration; dual-catalog support).
  - August: public beta for new self-serve signups (no forced migrations).
  - September: opt-in migrations for SMB and mid-market at renewal; enterprise migrations remain contractual/renewal-bound.

Guardrails for this decision
- Churn impact: limit any absolute logo-churn increase to ≤1 percentage point during the transition period.
- Gross margin: stay ≥78% during and after rollout through careful meter pricing and guardrails.
- Sales velocity: avoid >10% deterioration in win rates or sales cycle length.
- Predictability: provide clear usage tiers, budget caps, or commitment bundles to avoid bill shock; ensure sales can quote predictably.

Key open choices for usage model
- Candidate value metrics: automations run per month (primary), API calls per month (secondary), or hybrid bundles (committed base + overage).
- Catalog structure: keep seat-based for collaboration features and add a usage component for execution volume, or move fully to usage-based with role-based add-ons.
- Rollout sequencing: new logo self-serve first, then opt-in renewals for SMB/MM, with enterprise negotiated migrations tied to contracting.

Decision context
- The question is whether to switch from seat-based pricing to usage-based billing in Q3 2026 and, if so, how to minimize churn while preserving gross margin and sales velocity given operational constraints (no mid-cycle proration until Q4, notice periods, and current billing capabilities). The data suggests value is more tightly tied to execution volume than to seats, but predictability and enterprise procurement norms must be respected. A dual-motion approach (seats + usage or committed usage bundles with caps) may balance alignment-to-value with predictability.