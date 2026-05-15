# Weekly Learnings

TopicID: T1
Context: Spiked on producing exactly-once semantics with Kafka; worried about out-of-order events and retry storms.
Question: For payments, would you recommend outbox pattern plus idempotency keys at the gateway, or is there a simpler approach you trust in production?

Notes: Derived latency budget is 250ms p95; compensating transactions are discouraged.

---

TopicID: T2
Context: Our monorepo uses a shared CI; feature flags may require cross-service coordination and auditability.
Question: How do you structure feature flags to minimize blast radius and ensure rollback across services?

Notes: Considering LaunchDarkly vs. homegrown; security wants change logs.
