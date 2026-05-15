# Operational Goals and SLAs

Align onboarding and operations with these goals for the Arbitrage Finder service.

## Business Goals
- Reliably detect and surface actionable crypto arbitrage opportunities with low false positives.
- Minimize missed opportunities through fast, accurate detection and robust operations.
- Maintain strong security and compliance while keeping operational overhead low.
- Manage cost efficiency and resource usage without compromising performance.

## SLAs
- Uptime: 99.95% monthly.
- Detection latency: p95 ≤ 250 ms from market event ingestion to arbitrage signal emission.
- Alerting: Incident alerts must fire within 2 minutes of threshold breach.
- MTTR: ≤ 30 minutes for priority incidents.
- Change failure rate: < 5% of production deploys.

## SLOs
- Error rate: < 0.2% failed detections or processing errors.
- Missed events: < 0.5% of qualified arbitrage opportunities.
- Resource targets: p95 CPU ≤ 70%; memory watermark ≤ 75%; GC pauses not to exceed 50 ms p99 for detection workers.
- Backlog: Event queue wait time ≤ 500 ms p95; sustained backlog not exceeding 1 minute without auto-scaling response.

## KPIs
- Throughput: Events processed per second and signals emitted per minute.
- Cost per million events: Track and optimize.
- False positives vs true positives: Weekly review and tuning.
- Time-to-detect: Distribution across p50/p95/p99.
- Stability: Number of rollbacks and incident count per quarter.

## Operational Practices
- On-call rotations: Follow-the-sun weekly rotations with clear handoff checklists.
- Release cadence: Weekly releases with canary rollouts and automated regression checks.
- Performance reviews: Monthly performance and capacity review against SLOs.
- Security reviews: Quarterly review of access controls, audit logs, and dependency updates.