# Release Readiness Dashboard — Project Brief

## Summary
Build an internal web service and API that aggregates signals from our delivery pipeline (build status, test coverage, open release-blocking issues, performance budget compliance, and change management checks) to compute a single “readiness score” and surface a clear go/no-go indicator for a pending release. The service is read-mostly and will be used by engineers and release managers before cutting a release.

## Goals
- Provide a single-pane view of readiness for a given service, branch, or release candidate.
- Compute a deterministic readiness score based on weighted criteria (builds, coverage, open blockers, perf budgets, approvals).
- Offer a small set of REST endpoints for UI and automation: readiness summary, criteria breakdown, history.
- Display a minimal internal web UI that mirrors the API data for human consumption.
- Retain 30 days of historical readiness snapshots for trend inspection.

## Scope (MVP)
- Ingest input artifacts from the CI system as JSON payloads (build summary, test coverage summaries, performance budget checks, and a list of blocking issues).
- Calculate and expose:
  - readiness_score: 0–100
  - status: “green” | “yellow” | “red”
  - criteria_breakdown: each component with pass/fail and weight
- REST endpoints (paths indicative, final contract TBD):
  - GET /readiness?service=<id>&ref=<branch_or_tag>
  - GET /readiness/history?service=<id>&days=30
  - GET /criteria?service=<id>&ref=<branch_or_tag>
- UI (simple, internal-only): service selector, current readiness, criteria breakdown, last updated timestamp.
- Manual override with reason and audit trail (for exceptional cases), visible in the breakdown and history.

## Out of Scope (MVP)
- Complex role-based access control (internal token + reverse proxy is sufficient for MVP).
- Notifications, chat integrations, or automated deploy triggers.
- Advanced analytics beyond 30 days of trends.

## Team & Timeline
- Team size: 3 engineers (2 backend, 1 full-stack) + 1 PM (part-time)
- Timeline: 3 weeks for MVP; 2 weeks hardening; pilot with internal platform team in week 6
- Work hours: 50–60 engineering hours/week across the team

## Stake Level
- Medium stakes: internal-facing dashboard that informs ship decisions. Reversible and does not handle payments or customer PII. Incorrect data could delay or unblock a release improperly, but impact is contained within engineering operations.

## Users
- Primary: Internal engineers and release managers.
- Secondary: QA leads verifying readiness criteria.

## Data Sensitivity
- No PII, no customer data. Only build metadata, test metrics, and counts of issues.
- Service must still follow secure coding practices: no secrets in code, proper input validation, least privilege for storage.

## Constraints & Conventions
- Types-first and small-file architecture.
- Max file length: 300 lines. Max function length: 50 lines.
- No new dependencies without explicit approval by the tech lead.
- Prefer pure utility functions for calculations; keep side effects isolated in services.
- Config via environment variables injected by runtime (no hardcoded secrets).
- Simple persistence layer is acceptable for MVP (e.g., lightweight relational file store or embedded DB); must support 30-day retention and simple querying.

## Acceptance Criteria (MVP)
- Readiness Score:
  - Deterministic calculation using a weighted formula:
    - build_pass (weight 0.4) — boolean pass/fail
    - test_coverage (weight 0.3) — pass if >= threshold (from config)
    - perf_budgets (weight 0.2) — pass if all budgets met
    - blocking_issues (weight 0.1) — pass if zero open “blocker” labels
  - status threshold: green >= 90, yellow 70–89, red < 70
- API:
  - GET /readiness responds in <300ms p95 under 50 concurrent requests with cached data.
  - GET /criteria returns the latest breakdown with timestamps and sources.
  - GET /readiness/history returns last 30 days of daily snapshots for the service/ref.
- UI:
  - Displays service/ref, readiness score, status, criteria breakdown, and last updated time.
  - Responsive and readable on laptop and standard external monitor.
- Data Freshness:
  - Ingested signals no older than 2 minutes for current readiness.
- Security:
  - Internal-only (behind company network / reverse proxy). Require internal token header for API.
  - No secrets in code or logs; inputs validated against schemas.
- Testing:
  - 85%+ coverage overall. Critical path (readiness calculation and criteria evaluation) has test-first coverage: happy path, thresholds, and edge cases.
- Reliability:
  - SLO 99.5% monthly for API availability (internal).
  - Graceful degradation: if a single signal is missing, mark that criterion as “unknown” and reflect in score and status per policy (documented fallback).

## Risks & Notes
- Ambiguous decision on data flow: compute-on-read vs precompute/caching vs event-driven updates (see ambiguous-decision.md).
- Data model versioning needed for future extension of criteria.
- Manual override must be auditable and not silently alter raw metrics.

---