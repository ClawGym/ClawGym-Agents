# Operations: SLOs and Escalation

Service Level Objectives (SLOs)
- SLO: 99.9% successful index builds complete within 15 minutes of trigger.
- SLO: Median search latency < 150 ms; 95th percentile < 500 ms for common queries.
- Error budget: Page on-call if the monthly error budget exceeds 5% of target SLOs.

Incident management
- Incident severity:
- SEV-1: Index failure or search outage impacting all users.
- SEV-2: Degraded search (e.g., stale results) or partial index corruption.
- SEV-3: Minor issues (e.g., slow build for a subset of notes).

Escalation steps
- Step 1 (Acknowledge): Acknowledge the pager within 5 minutes.
- Step 2 (Mitigation): Roll back to the last known-good index and disable new writes if needed.
- Step 3 (Escalation): Escalate to the search lead if unresolved after 15 minutes.
- Step 4 (Communication): Update #search-ops Slack channel and status page.
- Step 5 (Recovery): Rebuild the index and verify fresh results.
- Step 6 (Post-incident): Publish a post-incident report within 24 hours.

On-call and pager
- Pager: PagerDuty schedule “search-oncall”, weekly rotation.
- Coverage: Business hours primary, after-hours secondary with escalation policy.
- Runbook: Linked from internal dashboard; includes commands for index rebuilds and log capture.

Monitoring and alerts
- Heartbeat: Index builder heartbeat every 5 minutes; alert if missed twice.
- Error rates: Alert when build errors exceed 1% over 15-minute windows.
- Latency: Alert on sustained p95 > 500 ms for 10 minutes.

Operational safeguards
- Backups: Last three successful builds retained for rapid rollback.
- Safe mode: TF-IDF-only mode if embeddings fail, to reduce incident blast radius.
- Access: Only on-call engineers have privileges to modify production indices.