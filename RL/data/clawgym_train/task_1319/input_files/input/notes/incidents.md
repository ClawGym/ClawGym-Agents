# Incident Log

## 2025-03-17 — Elevated 5xx errors on metadata service
Summary: Users experienced elevated 5xx errors and slow responses from the metadata API between 14:03 and 14:27 UTC.
Impact: Approximately 18% of requests to /v1/metadata/list failed or exceeded 5s latency in us-east-1.
Detection: Automated SLO alert fired and on-call acknowledged within 2 minutes.
Root cause: exhausted Postgres connection pool due to runaway debug queries.
Mitigation: Rolled back the debug feature flag, terminated long-running queries, and doubled connection pool temporarily.
Follow-up: Add query guardrails, reduce pool size per replica, and implement connection leak detection.

## 2024-12-02 — WebSocket reconnect flapping
Summary: Clients experienced reconnect loops due to a token refresh bug.
Root cause: Premature token invalidation after clock skew adjustments.
Mitigation: Hotfixed token refresh logic and tuned clock drift thresholds.