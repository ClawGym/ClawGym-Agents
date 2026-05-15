# Incident Report: APAC Teams Service Degradation (SEV-1)

Date: 2026-03-12  
Start: 02:10 UTC  
End: 04:35 UTC  
Duration: 2h 25m

Scope:
- Regions affected: APAC (primary impact), minor spillover to EMEA edge PoPs for <10 minutes
- Impacted services: Teams creation, Teams sync, invite flow (Teams plan only)
- Affected users: ~28% of active Teams organizations in APAC during the window
- Support volume: ~600 tickets referencing failed team creation or sync
- Data loss: None confirmed

Customer Impact:
- Users could not create new teams or sync membership. Attempts returned 5xx or timeouts.
- Admin dashboards showed inconsistent status during the first 20 minutes.
- Several SMB customers reported delaying broader rollout decisions.

Root Cause:
- Mis-scoped feature flag for "Teams Sync Accelerator" rolled to 100% in APAC shard.
- Redis cluster memory pressure and hot-shard formed due to uneven key distribution.
- Autoscaling thresholds were set for average load; did not trigger during early spike.

Detection:
- Synthetic checks triggered alerts at 02:12 UTC.
- Elevated 5xx rate visible in dashboards; SRE on-call paged immediately.

Mitigation:
- Rolled back feature flag at 02:25 UTC (partial relief).
- Increased Redis memory and rebalanced shards by 03:05 UTC.
- Full recovery verified at 04:35 UTC.

Contributing Factors:
- Pre-production load tests did not include APAC-specific traffic patterns.
- Feature flag config allowed region-wide 100% rollout without ramp guards.

Actions Taken:
- Added region-specific canary guardrails to feature flags (completed 2026-03-18).
- Implemented shard balancing automation and hot-key detection (completed 2026-03-20).
- Raised autoscaling sensitivity for APAC clusters (scheduled deploy 2026-04-05; completed 2026-04-05).
- Expanded pre-prod load tests with APAC traffic replay (in place 2026-03-25).

SLO / Error Budget:
- Consumed ~35% of monthly error budget for APAC Teams within the incident window.
- Global SLO remained within target for March; APAC Teams SLO breached for March.

Risk Assessment:
- Residual risk: Low-to-moderate for APAC pending continued monitoring through April.
- Confidence in mitigation: Medium-high after autoscaling update deployed 2026-04-05.

Customer Communication:
- Status page updated at 02:20 UTC; RCA posted 2026-03-15.
- Proactive outreach to top APAC accounts with credits where applicable.

Notes:
- Price-sensitive SMBs in APAC referenced this incident in renewal and upgrade conversations.