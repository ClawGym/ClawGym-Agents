# Stakeholders — Telemetry360

## Internal

- Name: Elena Rossi
  Role: Product Lead
  Priorities:
    - MVP in 12 weeks with must-have ingestion, dashboards, and alerting
    - Usable UX for analysts and quick time-to-first-dashboard
    - Pricing/usage metrics ready for design partners
  Success Criteria:
    - 10 design partners live with dashboards under 2s p95 (24h range)
    - Alerting functional with at least email + webhook
  Concerns:
    - Over-engineering (premature microservices) delaying MVP
    - Scope creep from custom tenant requests

- Name: Markus Vogel
  Role: CTO
  Priorities:
    - Clear migration path from MVP to scale (10x EPS)
    - Strong module boundaries, testability, and observability
    - EU data residency and secure-by-default posture
  Success Criteria:
    - Clean separation of concerns (ingest, process, query, admin)
    - Infrastructure-as-code, canary deploys, and SLOs wired to alerts
  Concerns:
    - Operational complexity of early microservices
    - Cost blowouts from poorly tiered storage

- Name: Sofia Novak
  Role: Head of Data Platform
  Priorities:
    - Efficient time-series writes and queries with rollups/downsampling
    - Backfill and reprocessing capability without major downtime
  Success Criteria:
    - Hot (14d) queries p95 < 2s; rollups running hourly under budget
  Concerns:
    - High-cardinality tags exploding storage
    - Choosing the wrong analytics store

- Name: Lukas Steiner
  Role: Security & Privacy Officer (DPO)
  Priorities:
    - GDPR compliance day 1; SOC 2 Type 1 in 9 months
    - EU-only data processing/storage with strong audit trails
  Success Criteria:
    - Encryption at rest and in transit; immutable audit logs
    - Documented data subject request workflows
  Concerns:
    - Any vendor without clear EU residency/SCCs
    - Weak tenant isolation leading to data leakage

- Name: Priya Mehta
  Role: SRE/DevOps
  Priorities:
    - Reliable deployments, rollback, infrastructure as code
    - Clear on-call with actionable alerts and runbooks
  Success Criteria:
    - Canary pipeline; <2h mean time to restore for P1
  Concerns:
    - Maintaining a Kafka cluster vs using managed
    - Hidden single points of failure

- Name: Daniel Kraus
  Role: CFO
  Priorities:
    - Keep MVP infra spend under €15k/month
    - Predictable cost per tenant and clear unit economics
  Success Criteria:
    - Storage tiering and compression in place
  Concerns:
    - Unbounded ClickHouse/Postgres growth

## External (Design Partners)

- Name: Marie Dubois
  Role: Enterprise Customer Admin (Energy sector)
  Priorities:
    - SAML SSO, RBAC, audit logs
    - Data residency in EU with signed DPA
  Success Criteria:
    - Dashboards embeddable in internal portal
    - Alert webhooks with signed HMAC and retries
  Concerns:
    - Query performance on 30-day windows during incidents

- Name: Jan Müller
  Role: Operations Manager (Logistics)
  Priorities:
    - Stable ingestion during spikes (firmware rollouts)
    - Easy device onboarding and API key management
  Success Criteria:
    - Ingest p99 < 1.5s; near-zero drops at 50k EPS peak
  Concerns:
    - Rate limiting that blocks critical telemetry

## Decisions Already Signaled

- Start with a modular monolith for MVP if it reduces time-to-market; keep strict module boundaries and contracts
- Prefer Postgres for metadata/control plane; evaluate ClickHouse vs TimescaleDB for metrics
- Managed Kafka/Redpanda in EU preferred over self-hosted
- AWS preferred; GCP acceptable if EU-only is guaranteed

## Open Questions (Need Resolution)

- Single database with tenant_id + RLS vs per-tenant schema for metadata?
- Per-tenant encryption keys (KMS) at GA or MVP?
- MQTT broker strategy: hosted by us vs customer-provided with push
- Which SSO vendor (Keycloak self-hosted vs Auth0 EU) for launch?