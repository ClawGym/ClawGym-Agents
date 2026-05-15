# Project Alpha — Working Notes

Last edited: 2026-04-07 10:18 UTC
Client: Transport Rino

## Roles and Ownership
- Product/PM Owner: Alice Nguyen
- Engineering Lead: Marco Diaz
- QA Lead: Jenna Park

## Timeline
- Kickoff: 2026-02-12
- Design freeze: 2026-04-15
- API freeze: 2026-05-05

## Decisions and Deadlines
- 2026-04-03: Tentative delivery deadline set to May 15, 2026 (internal target; pending client confirmation).
- 2026-04-07: Final deadline moved to May 20, 2026 after client confirmation on the weekly sync. This supersedes the May 15 tentative target.

## Scope Notes
- MVP includes: authenticated dashboard, shipment tracking, CSV export, and alerting.
- Out of scope for MVP: mobile app, real-time GPS overlays.

## Tech Stack
- Backend: FastAPI (Python 3.11)
- Database: Postgres 15
- Caching: Redis (for rate-limited endpoints)
- CI/CD: GitHub Actions → Fly.io
- Observability: Sentry (errors), Prometheus (metrics), Grafana (dashboards)

## Quality Gates
- Unit test coverage gate: 85% minimum on backend required for merge to main.
- Lint rules: Ruff + Black; no warnings allowed in CI.
- Performance: P95 dashboard load < 800 ms on staging data set.

## Preferences and Practices
- Code reviews require 2 approvers for backend changes.
- Use UTC timestamps in logs and audit fields.
- Feature flags via Flipper; default off until QA sign-off.

## Risk and Mitigations
- Risk: shipment data spikes around monthly close (last 3 business days). Mitigate with Redis-based request throttling and job queue backoff.

## Notes from 2026-04-07 Weekly Sync
- Client (Transport Rino) confirmed the public beta window for the week of May 20.
- Confirmed on-call rotation for first 72 hours after launch (Marco, then Jenna).