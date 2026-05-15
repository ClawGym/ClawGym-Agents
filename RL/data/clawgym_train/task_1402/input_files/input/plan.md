# Internal Cross-Service Notifications Platform — Rough Proposal (v0.3 draft)

Author: Platform Engineering (Notifications Working Group)
Date: 2026-04-10
Company: Northstar Tech, Inc.

## 1) Purpose and Context

We have 40+ microservices (Identity, Billing, Orders, Shipping, Support, Mobile, Web, etc.) emitting user- and system-facing events. Today, each team hand-rolls their own notification logic per channel (email, push, Slack, in-app), leading to inconsistent user experiences, duplicated messages, compliance gaps, and brittle integrations with providers.

This proposal sketches an internal, multi-tenant notifications platform to centralize event ingestion, routing, user preferences, templating, and delivery across channels. It aims to provide consistent behavior and observability while letting product teams move faster.

## 2) Goals (P0/P1)

P0 (must-have for initial GA):
- Central event ingestion API with at-least-once delivery to downstream channels.
- Unified routing engine with topics, subscriptions, and rules.
- User preferences and quiet hours honored across all channels.
- Templating service with variables, partials, and localization (L10N).
- Delivery adapters for: Email (SendGrid), Mobile Push (APNs/FCM via Unified Push gateway), In-app Inbox (web/mobile).
- Observability: end-to-end trace ID, per-notification status lifecycle, metrics and dashboards.
- Compliance: unsubscribe/consent flows, GDPR/CPRA alignment, data retention policy.
- Idempotency/dedup: prevent duplicate sends across retries.

P1 (post-GA enhancements):
- Slack/MS Teams adapters (for internal staff notifications).
- Multi-region active-passive with RPO ≤ 5 minutes.
- Rules UI for product ops (non-engineering) to manage audiences, throttles, and experiments.
- A/B template experiments.

Non-goals (explicitly out of initial scope):
- Marketing/broadcast campaigns at >100k fan-out per blast (owned by Growth).
- External partner integrations beyond company-controlled channels.
- Real-time ML personalization (may revisit later).

## 3) Stakeholders

- Platform Eng (owners/builders)
- Product Teams: Orders, Billing, Support (early adopters)
- Security/Compliance (DPO, Privacy)
- SRE (on-call, reliability)
- Data (event schema governance)
- Customer Experience (content and tone)

Hidden stakeholders (to verify): Legal (re: transactional vs marketing), Localization team, Mobile push ops, Finance (SendGrid cost oversight).

## 4) Assumptions

- Cloud: AWS primary region (us-east-1); second region (eu-central-1) for data residency and DR.
- Core stack: Kafka for high-throughput events, Postgres for operational state, Redis for rate limiting, S3 for template assets.
- Identity: OIDC service-to-service auth (mTLS between trusted services).
- Email provider: SendGrid (existing enterprise contract).
- In-app inbox will be rendered by Web and Mobile apps via a new Notifications API and WebSocket feed.

## 5) High-Level Architecture (proposed)

Components:
1. Ingestion API
   - HTTP: POST /v1/events
   - Kafka topic: notifications.events.v1 (optional producer path)
   - Validates schema; enqueues to Kafka for durable fan-out.

2. Router & Rules Engine
   - Subscriptions: user or segment subscribes to a Topic within a Tenant.
   - Rules: map Topic + context → channel list; enforce preferences, quiet hours, throttles.
   - Outputs ChannelTasks (EmailTask, PushTask, InboxTask).

3. Preferences Service
   - Stores per-user consent, quiet hours, channel opt-ins/outs, and per-tenant overrides.
   - Policy API for “allowed by default” vs “opt-in only” by topic.

4. Template Service
   - Versioned templates with locale fallbacks and shared partials.
   - Variables mapping from event payload; preview and validation.

5. Delivery Adapters
   - Email (SendGrid)
   - Push (APNs/FCM through existing push gateway)
   - In-app Inbox (persist + WebSocket)

6. Notification Store
   - Durable notification records with lifecycle: queued → rendered → sent → delivered → failed → suppressed → bounced.
   - Idempotency and dedup keyed by (tenant_id, dedup_key, time_window).

7. Observability
   - Tracing (trace_id from headers), metrics, per-recipient audit log, dead-letter queues (DLQ) for poison messages.

Data flow summary:
Producer → Ingestion (HTTP/Kafka) → Kafka bus → Router/Rules → ChannelTasks → Adapters → Providers/Inbox → Status updates back to Notification Store.

## 6) Data Model (initial sketch)

Entities (initial):
- Tenant(id, name, slug)
- Topic(id, tenant_id, key, description, required_consent: enum)
- Event(id, tenant_id, topic_key, actor_user_id?, target_user_ids[], payload JSON, priority, idempotency_key?, dedup_key?, ttl_sec, compliance_tags[], trace_id, created_at)
- Subscription(id, user_id, tenant_id, topic_key, channels[], state: subscribed|unsubscribed|forced, updated_at)
- Preference(id, user_id, tenant_id, channel, quiet_hours: cron or window, overrides JSON)
- Template(id, tenant_id, channel, locale, version, status: draft|active|retired, schema JSON, body, subject)
- Notification(id, event_id, user_id, tenant_id, topic_key, status, created_at, updated_at)
- ChannelMessage(id, notification_id, channel, provider_message_id?, status, error_code?, sent_at, delivered_at, bounced_at)
- RateLimitPolicy(id, tenant_id, key, window, max, scope: per_user|per_tenant|global)

Validation rules (examples):
- Event.topic_key must exist for tenant.
- If Topic.required_consent == opt_in, Subscription.state must be subscribed for at least one channel unless override = transactional.
- Template.active must exist for channel+locale or fallback to default locale.
- Quiet hours suppress non-urgent notifications unless priority = critical.

## 7) Interfaces (draft)

HTTP Ingestion:
POST /v1/events
Headers: X-Tenant, X-Trace-Id, Idempotency-Key (optional), Authorization (mTLS+OIDC)
Body:
{
  "topic": "order.shipped",
  "actor_user_id": "u_123",
  "targets": ["u_456"],
  "payload": {"orderId": "o_789", "carrier": "UPS", "tracking": "1Z..."},
  "priority": "normal",
  "dedup_key": "order:shipped:o_789:u_456",
  "ttl_sec": 86400,
  "compliance_tags": ["transactional"]
}

Notification Query:
GET /v1/users/{user_id}/notifications?status=unread&limit=50
WebSocket: /v1/users/{user_id}/stream (JWT auth from Identity)

Internal Events:
- notifications.notification.status.changed (Kafka) for analytics.

## 8) Non-Functional Requirements (targets)

- Throughput: sustained 500 notifications/sec; peak 2,000/sec for 15 minutes.
- Latency SLO (enqueue→adapter send): P95 ≤ 1.0s for inbox/push, ≤ 3.0s for email.
- Availability: 99.9% monthly for ingestion and API reads; channel adapters best-effort.
- Durability: no data loss for accepted events (WAL + Kafka).
- Cost guardrails: <$35k/month infra + providers for initial scale.
- Security: encryption at rest (AWS KMS) and in transit (TLS), scoped secrets per adapter, audit trails for admin changes.
- Data residency: EU data for EU users (TBD details).
- Retention: Notification records 13 months; Channel payloads 90 days masked.

## 9) Operational Concerns

- Backpressure: queue length alarms, adaptive throttles, per-tenant quotas.
- Retries and DLQ: exponential backoff with jitter; poison message quarantine with manual replay.
- Idempotency: dedup window default 1 hour per dedup_key.
- Rate limiting: per-user and per-tenant, channel-specific limits.
- On-call: PagerDuty rotation owned by Platform; playbooks; synthetic checks.
- Schema evolution: versioned topics; producer lints; consumer tolerates additive fields.

## 10) Compliance and Privacy

- Transactional vs marketing classification; ensure appropriate unsubscribe and consent checks.
- DSAR support: delete/minimize user-identifiable content while preserving audit trail.
- DPA with SendGrid already in place; review push provider compliance.
- Data mapping for EU residency (subject to design).

## 11) Phased Rollout

- Alpha (2 sprints): Inbox + Email for Orders (“order.shipped”, “order.delivered”).
- Beta (4 sprints): Add Push; onboard Billing and Support; start preferences UI.
- GA: Hardened reliability, rate limiting, localized templates for EN/ES/DE.

## 12) Open Questions (needs decisions)

[OQ-01] Scope: internal-only use vs exposing to external partners later?
[OQ-02] Delivery semantics per channel: exactly-once vs at-least-once vs effectively-once via dedup?
[OQ-03] Multi-region strategy: active-active or active-passive for GA?
[OQ-04] Enqueue→send latency SLOs per channel (final numbers)?
[OQ-05] Preference defaults: opt-in or opt-out per topic class; how to define “transactional override”?
[OQ-06] Quiet hours policy: global defaults vs per-tenant; critical override rules?
[OQ-07] Notification retention: hard delete vs soft delete + tombstone for DSAR?
[OQ-08] In-app inbox retention and unread cap behavior?
[OQ-09] DSAR coverage: what exact fields are erased vs hashed?
[OQ-10] Per-user and per-tenant rate limits: baseline values?
[OQ-11] DLQ handling: who owns replay, do we need an admin console at GA?
[OQ-12] Template localization: fallback order and version pinning strategy?
[OQ-13] Access model: who can define topics/rules per tenant; approval workflow?
[OQ-14] Triple constraint: if deadlines tighten, which scope items move to P1?
[OQ-15] Pager severity mapping: when does a channel outage page vs ticket?

## 13) Initial Success Signals (proposed)

- By end of Q3: 3 product teams live; ≥60% of their transactional notifications routed via platform.
- Duplicate email sends reduced by ≥50% for Orders topics (baseline: Jan 2026).
- P95 end-to-end latency ≤ 1.0s for inbox/push and ≤ 3.0s for email for 95% of topics.
- >99.5% preference compliance (no sends in quiet hours except critical).
- Observability: 100% of notifications carry a trace_id; alert MTTA ≤ 10 minutes.

Risks (known):
- Provider outages; template complexity; preference edge cases; multi-region cost/complexity.