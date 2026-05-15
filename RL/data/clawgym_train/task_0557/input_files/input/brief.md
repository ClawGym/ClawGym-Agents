Context Memo: Q4 4-Day Workweek Pilot (32 hours, full pay)

Objective
- Decide whether to run a 10-week pilot in Q4 2026 (Oct 7 – Dec 20) for a 4-day, 32-hour workweek (full pay) for Product Engineering, Platform, and Design. People Ops and FinOps provide advisory support. Support Tier-1 and Sales are excluded due to coverage and quota constraints.

Constraints and Guardrails
- Coverage: Maintain 5-day support coverage and 24x5 on-call. Ops may stagger off-days (e.g., Mon/Thu off rotation) to ensure Friday coverage.
- Legal/Compliance: Non-exempt roles must remain compliant with wage/hour rules. No off-the-clock work. Review local labor laws (US/EU/UK).
- Budget: No additional headcount. Overtime and contractor spend should not exceed Q3 average by >3%.
- Deliverables: Mid-November release includes two critical features (Feature A: billing revamp; Feature B: SSO enhancements). Code freeze window and release readiness cannot slip.
- Communication: Outcomes-based expectations; no implied “cram 40 into 32.” Managers must adjust sprint capacity planning accordingly.

Baseline Data (Q3 2026)
- Engineering throughput: Median 21 story points/dev/week; cycle time median 4.2 days; WIP limit 4.
- Incidents: P1 MTTD 6m, MTTR 42m; P2 MTTR 3.5h.
- Support SLAs: First response within 1h (95th percentile met).
- People metrics: 17% considered “high burnout risk” in pulse survey; retention rolling 12-month attrition 12.8%; recruiting pipeline acceptance rate +9% for roles advertising flexibility.
- Financials: Revenue steady; gross margin 66%; contractor spend 2.1% of engineering payroll.

Pilot Parameters to Consider
- Schedule: Default Friday off for pilot teams; Ops/Infra stagger to preserve coverage. Option for “core hours” Tue–Thu 10:00–3:00 local for cross-team collaboration.
- Measurement: Compare against Q3 baselines and first 3 weeks of Q4 (pre-pilot warm-up) for seasonality.
- Tooling: Update sprint capacity (–20% hours, not –20% outcomes), enforce WIP limits, and reserve 10% time for retros and coordination.
- Risks: Holiday compression, cross-timezone sync loss on Fridays, possible context-switch friction.

Success Criteria (Pass/Fail)
- Productivity: ≥95% of baseline throughput and stable cycle time (±10%).
- Reliability: P1 MTTR ≤ 46m; no SLA erosion on first response.
- People: +15% improvement in work-life balance; ≥5% reduction in “high burnout risk.”
- Cost: Overtime + contractors ≤ +3% vs Q3; no revenue impact from delayed features.

Decision Signals
- Pro signals: Prior research suggests reduced burnout, higher focus blocks, and hiring edge. Our recruiting data already indicates flexibility boosts acceptance.
- Con signals: Coordination overhead may rise; Friday stakeholder availability may drop; Ops risk if staggering fails.

If Approved (High-Level Plan)
- 2-week prep (capacity recalibration, coverage schedules, legal sign-off).
- 10-week pilot with weekly check-ins and mid-pilot review.
- Metrics dashboard aligned to success criteria.
- Exit criteria: End pilot if any critical SLA breaches persist >2 weeks or if release risk is high.

Recommendation Note
- Favor proceeding if risk mitigations (staggered Ops schedule, core hours, sprint capacity recalibration) are in place and metrics can be tracked weekly with rollback authority delegated to Ops and Eng leadership.