# Company Profile: PayForge Inc. — B2B Payments API Launch (US & EU)

## Overview
PayForge Inc. is a mid-stage fintech providing payments infrastructure for B2B platforms and SaaS vendors. We are launching a unified Payments API enabling:
- US ACH (same-day and standard) and domestic wire
- EU SEPA Credit Transfer (and SEPA Instant where partner banks support)
- Cross-border payouts with FX quoting and conversion
- Real-time webhooks for payment status and reconciliation
- Idempotent write operations and sandbox/test-mode features

Target customers are mid-market and enterprise software platforms that embed accounts payable and vendor payments.

Primary regions for GA: United States and European Union. Production hosting:
- US region: AWS us-east-1
- EU region: AWS eu-west-1 (EU data residency enforced; PII and payment data stay in-region)

## Timeline & Milestones
- Current phase: Private Beta (15 design partners live on US ACH)
- EU pilot start: 2026-06-10 (limited SEPA volume with two partner banks)
- Code freeze: 2026-07-15
- Readiness review: 2026-08-01
- Target GA launch (US + EU): 2026-08-31
- Change freeze window: 2026-08-15 to 2026-09-07 (critical-path approvals required for any prod changes)

## Functional Scope for GA
- Create payment instructions (ACH, wire, SEPA)
- Payment status query and webhook notifications
- Counterparty management with KYC/KYB checks
- FX quoting for cross-border payouts (spot only; no forwards at GA)
- Reconciliation exports and ledgering hooks

## Non-Functional Targets
- Availability SLO: 99.95% monthly
- Throughput at launch: ~2,000 requests/minute peak (US), ~1,200 requests/minute peak (EU)
- Latency targets: p95 < 300ms for reads, p95 < 600ms for writes (excluding bank processing delays)
- Data residency: EU personal data stored and processed only in eu-west-1
- Security posture: Encryption in transit (TLS 1.3), encryption at rest (KMS), HSM-backed key management for token vaults

## Regulatory & Compliance Context
- EU: GDPR, PSD2 (as a TPP partnership model; strong customer authentication where applicable), SEPA scheme rules
- US: NACHA operating rules (ACH), OFAC screening, applicable state money transmitter partner obligations
- Cross-cutting: PCI DSS SAQ A (tokenized approach; we do not store PAN), SOC 2 Type II in progress (external audit scheduled for late Q3 2026)

## Third-Party Dependencies
- Bank partner APIs (US and EU) — certification windows and scheme testing required
- KYC/KYB provider: KYCPro (primary), Onboardly (secondary/backup)
- Cloud: AWS (VPCs in us-east-1 and eu-west-1), managed Redis, RDS Postgres
- Observability: Datadog (logs, APM, metrics), PagerDuty (on-call)

## Known Concerns / Hotspots
- Rate limiting and adaptive DDoS controls are not fully tuned for EU endpoints
- SEPA file/message version alignment and partner-specific rules require careful validation
- KYC vendor single point of failure during peak onboarding windows
- FX quote cache staleness observed in past incidents; monitoring gaps previously identified
- Data classification and log redaction gaps (legacy services) — privacy risk if left unaddressed
- Change freeze window reduces capacity to respond to late-breaking issues

## Budget & Constraints (Pre-Launch)
- Risk mitigation budget cap (pre-launch): $500,000 total (includes $100,000 contingency reserved for regulatory/compliance response)
- Hiring constraints: Hiring freeze through GA; up to 2 contractor slots approved for pre-launch mitigation
- Vendor certification: US and EU bank partner certification windows close by 2026-06-30 (extensions unlikely)
- Parallel priorities: SOC 2 Type II evidence collection ongoing; minimize tooling churn

## Customers & Volume Expectations
- 50 signed customers committed for migration within 90 days post-GA
- Initial payment volume estimates:
  - US ACH: 25–40K transactions/day peak
  - EU SEPA: 10–20K transactions/day peak
- Expected mix: 85% ACH/SEPA batch, 15% same-day/instant where supported

## Lessons from Past Incidents
See input/past_incidents.csv for details. Key themes:
- Capacity management (Redis saturation) and defensive rate limiting
- Strict message/schema validation for SEPA artifacts
- Vendor dependency planning (circuit breakers, fallbacks)
- FX pricing staleness monitoring and reconciliation controls
- Privacy-by-design (PII in logs) and automated redaction

Please use this context along with constraints.yaml and past_incidents.csv when building the risk register, heat map, and summary.