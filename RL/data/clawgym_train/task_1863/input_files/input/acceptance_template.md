# Acceptance Criteria Template

Use this structure to write clear, testable acceptance criteria. Keep each item independently verifiable. Prefer measurable targets and explicit HTTP status codes, headers, and payloads.

## Sections to include

1. Scope
   - Briefly define what is in and out of scope.
2. Non-Goals
   - Call out anything explicitly not being delivered.
3. Acceptance Criteria (checkboxes)
   - Each line begins with "- [ ]" and is objectively verifiable.
4. Security & Compliance
   - List any auth, RBAC, logging, privacy, and rate limiting requirements.
5. Testing & Validation
   - Define unit, integration, and performance checks with thresholds.
6. Rollout & Monitoring
   - Staged rollout plan with gates and rollback conditions.

## Example (for operational endpoints)

Scope: Add a public health endpoint and a protected metrics endpoint.

Non-Goals: No database migrations; No changes to existing business APIs.

Acceptance Criteria:
- [ ] GET /healthz returns 200 with JSON body containing: status, version, commit, uptimeSeconds
- [ ] /healthz sets header Cache-Control: no-store
- [ ] /healthz is rate-limited to N RPM per client IP (configured via RATE_LIMIT_RPM_HEALTHZ); excess requests receive 429
- [ ] /healthz performs only lightweight in-process checks (no network calls or DB queries)
- [ ] p95 latency for /healthz ≤ 50ms under nominal load in CI integration test

- [ ] GET /metrics requires a valid JWT signed by configured issuer; requests without token are 401
- [ ] /metrics enforces RBAC: token must include role "<required-role>" (configurable via METRICS_RBAC_ROLE) or returns 403
- [ ] /metrics responds with Content-Type "text/plain; version=0.0.4" and supports gzip when requested
- [ ] Metrics labels contain no PII and avoid high-cardinality dimensions
- [ ] Successful /metrics scrape path is covered by integration tests using httptest

Security & Compliance:
- [ ] JWT is validated against JWKS from configured URL; expired or invalid tokens are rejected
- [ ] No secrets or bearer tokens are logged; logs are structured JSON
- [ ] RBAC checks are constant-time where applicable and do not leak role details in error messages

Testing & Validation:
- [ ] Unit tests cover new handlers and middleware with ≥80% coverage for changed code
- [ ] Integration tests validate 200/401/403/429 cases for new endpoints
- [ ] Tests run with race detector enabled where feasible
- [ ] OpenAPI updated for /healthz; /metrics documented as internal-only

Rollout & Monitoring:
- [ ] Feature flags (ENABLE_HEALTHZ_ENDPOINT, ENABLE_METRICS_ENDPOINT) control activation
- [ ] Staged rollout: canary (5%) → 25% → 100%, with gates on 5xx error rate, /healthz p95, and scrape success rate
- [ ] Clear rollback criteria and a one-command rollback path documented in the runbook

Tips:
- Keep each checkbox atomic and machine-verifiable.
- Use precise language ("returns 403") instead of vague ("access is restricted").
- Include configuration sources (env var names) where relevant.