# Service Overview

Name: orders-api (internal)
Purpose: Core order management service providing CRUD endpoints for orders and related artifacts. Designed for high-availability, low-latency internal traffic with a small surface of public-safe endpoints.

This feature request adds two operational endpoints:
- Public GET /healthz with lightweight checks and rate limiting
- Protected GET /metrics that requires role-based access control (RBAC) and is safe for automated scraping

# Tech Stack

- Language: Go 1.22
- HTTP router: github.com/go-chi/chi/v5
- Metrics: github.com/prometheus/client_golang v1.x
- Logging: github.com/rs/zerolog v1.x (structured JSON logs)
- AuthN/Z: JWT (RS256), verified against issuer JWKS; roles provided in token claims
- Rate limiting: github.com/go-chi/httprate
- Build: `go build` with modules
- Tests: `go test` (unit + integration via httptest), race detector enabled where feasible
- Deployment: Containerized, orchestrated on Kubernetes
  - Pods expose HTTP on PORT (default 8080)
  - Ingress provides TLS termination
  - Scraping performed by internal monitoring agents

# Current Architecture

- cmd/server/main.go — service bootstrap (router, middlewares, config, logger)
- internal/http/ — handlers, middlewares, router wiring
- internal/auth/ — JWT verification, RBAC helpers
- internal/metrics/ — registry and common metrics collectors
- internal/config/ — env var parsing, defaults
- api/openapi.yaml — API contract (public endpoints)

A Prometheus registry is initialized at process start (default). No explicit /metrics exposure is currently wired.

# Existing API (selected)

- GET /v1/orders — protected (JWT required; RBAC: orders.read)
- POST /v1/orders — protected (RBAC: orders.write)
- GET / — simple welcome (public), primarily for smoke tests

# Authentication & RBAC

- Tokens: JWT, RS256, issuer defined by ISSUER_URL
- JWKS auto-refresh: configured via JWKS_URL
- Roles: array in token claim "roles" (e.g., ["orders.read", "monitoring"])
- Helper: internal/auth.HasRole(ctx, "roleName") returns bool
- Audience: validated if AUDIENCE is set (optional but recommended)

# Observability

- Prometheus client registered (default registry)
- Common HTTP request metrics middleware in place (latency, status code)
- No /metrics endpoint currently exposed
- Logs: zerolog JSON, request-scoped fields (trace_id, method, path, status, duration_ms)

# Configuration (env vars)

- PORT (default: 8080)
- LOG_LEVEL (info|debug|warn|error)
- ISSUER_URL (required)
- JWKS_URL (required)
- AUDIENCE (optional)
- METRICS_RBAC_ROLE (default: "monitoring")
- RATE_LIMIT_RPM_HEALTHZ (default: 60)
- ENABLE_METRICS_ENDPOINT (default: true)
- ENABLE_HEALTHZ_ENDPOINT (default: true)

# Non-Functional Expectations

- Backward compatibility: No breaking changes to existing endpoints
- Latency targets:
  - /healthz: p95 ≤ 50ms under nominal load (lightweight checks only)
- Security:
  - /metrics must require RBAC (role: METRICS_RBAC_ROLE)
  - Do not leak secrets or PII in logs or metrics labels
  - JWT verification against JWKS; reject invalid/expired tokens
- Rate limiting:
  - /healthz rate-limited per IP (RPM defined by RATE_LIMIT_RPM_HEALTHZ)
- Documentation:
  - Update api/openapi.yaml for /healthz; /metrics may be documented as internal-only
- Testing:
  - Unit tests for handlers, middleware
  - Integration tests (httptest) for end-to-end behavior of new endpoints
  - ≥80% coverage for new/changed code
  - Run with -race for integration tests if stable

# Endpoint Requirements (new)

- GET /healthz (public)
  - Returns 200 with JSON payload:
    - status: "ok"
    - version: from build-time variable
    - commit: from build-time variable
    - uptimeSeconds: integer
  - Must avoid external calls or heavy checks (no DB ping)
  - Rate limited per client IP (RPM from env), return 429 on limit
  - Headers: Cache-Control: no-store
  - Add counters/histogram for requests and latency

- GET /metrics (protected)
  - Requires valid JWT with RBAC role METRICS_RBAC_ROLE (default "monitoring")
  - Exposes Prometheus text format using promhttp handler
  - Content-Type: text/plain; version=0.0.4
  - Support gzip compression when requested by client
  - Safe for scraping:
    - No high-cardinality or PII labels
    - Ensure handler performs minimal allocations
  - Deny requests without required role (401/403) and log at info with redacted details

# Rollout Notes

- Enable via ENABLE_HEALTHZ_ENDPOINT and ENABLE_METRICS_ENDPOINT
- Staged rollout (canary → 25% → 100%) controlled by deployment strategy
- Monitors:
  - 5xx error rate <1%
  - /healthz p95 latency
  - Scrape success rate ≥99%
- Fast rollback via previous deployment if SLOs regress