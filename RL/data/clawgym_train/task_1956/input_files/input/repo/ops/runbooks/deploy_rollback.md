# Runbook: Deploy Rollback

Scope:
- Web+API deployment rollback procedure for production incidents

Triggers:
- Elevated 5xx error rate
- Significant p95 latency regression
- Functional outage on critical paths (auth, payments)

Steps:
1. Freeze new deployments.
2. Identify last known good release (tagged in CI).
3. Roll back using `deploy rollback --to <tag>`.
4. Verify health endpoints and smoke tests.
5. Monitor dashboards for stabilization.
6. Create incident timeline and postmortem draft.

Contacts:
- On-call engineer
- Release manager
- SRE

Expected time to complete: 15 minutes.