# Incident Postmortem: API Latency Spike

Summary:
Between 14:03 and 14:21 UTC, the public API experienced elevated p95 latency. Client-facing SLAs were breached for 11 minutes.

Impact:
- 7% of requests exceeded 2s latency.
- No data loss reported; retries eventually succeeded.

Timeline:
- 14:03 UTC — Alert fired for sudden latency increase.
- 14:05 UTC — On-call acknowledged and began triage.
- 14:11 UTC — Mitigation applied (disable a new feature flag).
- 14:21 UTC — Latency returned to baseline.

Root Cause:
The immediate root cause was an unintended N+1 query introduced by a recent configuration change. The code path was activated only under a specific header condition, which expanded database load unexpectedly.

Contributing Factors:
- Missing database index on a frequently filtered column.
- Insufficient canary coverage for the header-conditioned path.

Detection:
- Alerting thresholds worked as designed, catching the spike quickly.

Corrective Actions:
- Add the missing index and backfill.
- Write a regression test that asserts the query count for the affected endpoint.
- Expand canary scenarios to include the conditional header.
- Document the root cause and review similar code paths for latent issues.

Lessons Learned:
- Feature flags that alter query patterns must have explicit safeguards.
- Dashboards should include query count breakouts per endpoint.