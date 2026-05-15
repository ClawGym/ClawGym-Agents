# Current Alert Inventory

This document lists existing alerts across services. Many alerts are infrastructure-centric; several lack a clear runbook and ownership, and some generate noise during routine operations.

API Gateway
- Alert: 5xx rate > 5% over 5 min
  - Signal: Ingress logs error rate
  - Owner: Platform Reliability
  - Runbook: Exists (needs update post 2026-03-05 incident)
- Alert: LB target unhealthy > 10% for 3 min
  - Signal: ELB target health
  - Owner: Platform Reliability
  - Runbook: Missing

Auth Service
- Alert: p95 login latency > 1200ms for 10 min
  - Signal: APM transaction latency
  - Owner: Identity Platform
  - Runbook: Exists
- Alert: CPU > 85% for 5 min
  - Signal: Host metrics
  - Owner: Identity Platform
  - Runbook: Generic (no action guidance)
- Alert: Redis hit rate < 80% for 10 min
  - Signal: Cache metrics
  - Owner: Identity Platform
  - Runbook: Missing

Marketplace Service
- Alert: 500 error rate > 2% on /search for 5 min
  - Signal: HTTP error logs
  - Owner: Commerce
  - Runbook: Exists (incomplete steps)
- Alert: Elasticsearch p95 query latency > 150ms for 10 min
  - Signal: Managed Elasticsearch metrics
  - Owner: Commerce
  - Runbook: Missing

Payments Service
- Alert: Stripe 429 responses > 1% for 5 min
  - Signal: Integration response codes
  - Owner: Fintech
  - Runbook: Exists (needs circuit breaker guidance)
- Alert: p95 authorize_charge latency > 400ms for 10 min
  - Signal: APM endpoint latency
  - Owner: Fintech
  - Runbook: Exists
- Alert: DB connections > 90% capacity for 10 min
  - Signal: RDS metrics
  - Owner: Fintech
  - Runbook: Generic

Notifications Service
- Alert: Kafka topic lag > 50k messages for 10 min
  - Signal: Consumer group lag
  - Owner: Engagement
  - Runbook: Exists
- Alert: SendGrid bounce rate > 2% for 15 min
  - Signal: Provider metrics
  - Owner: Engagement
  - Runbook: Missing
- Alert: p95 email send latency > 3s for 10 min
  - Signal: Application metrics
  - Owner: Engagement
  - Runbook: Exists

Analytics Service
- Alert: ETL job failure count > 3 in last hour
  - Signal: Job scheduler logs
  - Owner: Data Platform
  - Runbook: Exists (needs error classification)
- Alert: Dashboard data freshness lag > 2h
  - Signal: Freshness watermark
  - Owner: Data Platform
  - Runbook: Missing
- Alert: Kafka under-replication partitions > 5 for 10 min
  - Signal: Broker metrics
  - Owner: Data Platform
  - Runbook: Exists

Noise & Gaps
- Repeated CPU threshold alerts in Auth and Payments correlate with batch windows; little actionability.
- Several alerts lack a runbook or clear owner, leading to slow response during incidents.
- Symptom-based alerts for user journeys are present but need tuning to reduce false positives and reflect SLO threats.