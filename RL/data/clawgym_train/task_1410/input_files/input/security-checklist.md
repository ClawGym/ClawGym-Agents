# Production Graduation Checklist — Release Readiness Dashboard

Use this checklist to assess readiness across security, performance, reliability, and quality. Mark each item as pass, fail, or n/a and document concrete fixes where needed.

## P0 — Security (Must Fix)
- [ ] No hardcoded secrets (search for API keys, tokens, passwords)
- [ ] Input validation enforced on all external inputs (schema validation, reject unknown fields)
- [ ] Authentication required on all API endpoints (internal token header)
- [ ] Authorization checks (protect internal admin endpoints, manual override actions)
- [ ] HTTPS enforced at the edge (internal deployment assumption)
- [ ] Dependencies free of known critical/high issues
- [ ] Rate limiting enabled on public/internal endpoints
- [ ] CORS restricted appropriately for internal use
- [ ] Error responses do not leak stack traces or sensitive internals
- [ ] Logs redact secrets and do not contain PII

## P1 — Performance (Should Fix)
- [ ] p95 latency within target (<= 300ms) for main endpoints under expected load
- [ ] Caching strategy implemented and documented (TTL and invalidation)
- [ ] No unbounded queries; endpoints are paginated/bounded where applicable
- [ ] Efficient data access patterns (indexes or key-based lookups as needed)
- [ ] Loading states and predictable response shapes in UI
- [ ] Reasonable bundle size and server resource usage (internal footprint)

## P2 — Reliability (Should Fix)
- [ ] Graceful degradation policy implemented for missing signals
- [ ] Health checks implemented (/healthz, /readyz)
- [ ] Error handling with clear logging and useful error messages
- [ ] Config via environment, with sane defaults and validation
- [ ] Data retention policy implemented (30 days)
- [ ] Backup or export path for snapshots (as appropriate for MVP)
- [ ] Rollback strategy defined and tested

## P3 — Quality (Nice to Have)
- [ ] Overall test coverage >= 85%; critical modules >= 90%
- [ ] Linter and formatter configured and clean run
- [ ] Clear README with setup, run, and test instructions
- [ ] CI pipeline runs tests on push and blocks on failures
- [ ] Architectural docs for scoring and data flow
- [ ] Accessibility and basic responsiveness for internal UI

## Notes
- This service is internal-only and does not process PII.
- Manual override must be auditable: record actor, timestamp, reason, and prior state.
- Prefer reversible decisions for MVP; document migration path for storage or computation model.

---