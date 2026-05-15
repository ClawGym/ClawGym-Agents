# Postmortem: Production Deployment Incident — 2026-04-12

Status: Resolved
Severity: SEV-2
Service: Web app API (auth + trading endpoints)
Owners: Platform team
Primary stakeholders: Alex (boss, Head of Engineering), On-call engineers

Summary
- Between 14:07–15:12 ET, the API returned elevated 5xx errors (~21% at peak).
- Root cause was a regression in the request parsing layer introduced in PR #4827.
- We bypassed a required check and deployed without running the full CI test matrix.

Impact
- Users intermittently failed to log in or place trades.
- Approximately 1,800 requests failed; auto-retries mitigated some impact.
- No data loss. Increased support tickets during the incident window.

Timeline (ET)
- 14:07: Deploy v2026.04.12-1 to production using GitHub Actions.
- 14:11: Sentry begins alerting about spike in 500 errors.
- 14:14: PagerDuty page for on-call (Marco).
- 14:20: Canary rollback considered; blue-green fallback initiated.
- 14:27: Rollback to previous stable (v2026.04.05-3).
- 14:34: Error rates return to baseline.
- 15:12: Root cause confirmed; incident resolved.

Root Cause
- The PR included a refactor of middleware ordering. The integration test suite (pytest) would have caught the regression, but we skipped the “test” job in GitHub Actions to “save time” after a transient flake earlier in the day.
- Missing guardrails: the “tests required” branch protection was accidentally disabled for the main branch.

Detection
- Sentry error spike and Datadog dashboards alerted us within ~4 minutes of deployment.

Resolution
- Performed blue-green rollback to v2026.04.05-3.
- Re-ran full test suite locally (pytest) to reproduce and confirm the failure.
- Patched the middleware and re-ordered the parsing step; shipped as v2026.04.12-2 after tests passed.

Lessons Learned
- Negative: Skipping CI broke our safety net. Always run the full test suite before deploying.
- Improve canary coverage for middleware changes (route-level health checks).
- Reinstate the “CI tests must pass” protection in GitHub Actions.

What Went Well
- Rollback playbook was followed quickly.
- Monitoring (Sentry, Datadog) gave clear signals.
- Communications stayed coordinated in incident channel.

What Went Wrong
- Test job was manually bypassed.
- No pre-deploy checklist enforced for hotfixes.
- Canary didn’t exercise the affected code path sufficiently.

Action Items
- Re-enable and lock the required “test” job in GitHub Actions (owner: Priya; due: 2026-04-15).
- Add a mandatory pre-deploy checklist step to the release script (owner: Jordan).
- Expand integration tests for middleware ordering in pytest (owner: Me).
- Add a canary endpoint that exercises auth + trading routes end-to-end (owner: Marco).
- Document the rollback flow with screenshots in the runbook (owner: Me).

Tools referenced
- GitHub Actions (CI/CD)
- pytest (test runner)
- Sentry (error monitoring)
- Datadog (metrics)
- PagerDuty (on-call)
- Docker (build/deploy images)