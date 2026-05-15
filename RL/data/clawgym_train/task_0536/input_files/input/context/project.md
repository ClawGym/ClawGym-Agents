# Project Nimbus Analytics Dashboard

We build a multi-tenant SaaS analytics dashboard for small-to-mid teams. Core goals:
- Turn operational data into real-time charts, alerts, and summarized insights.
- Enable collaborative dashboard editing (commenting, shared filters, concurrent edits).
- Maintain strict security and compliance posture (SOC 2-lite controls, internal approvals).

## Current Architecture
- Frontend: Next.js 14 + React, TypeScript, Tailwind.
- Backend: Node.js 18 (Express, REST + WebSocket), Python microservices for data ingestion/enrichment.
- Data: PostgreSQL 15 (primary), Redis (caching), optional Kafka (managed) for event pipelines.
- Infra: Docker images, Kubernetes deployments, GitHub Actions CI/CD.
- Auth: OAuth2 / OIDC (Auth0), role-based access, audit logging.

## Near-Term Objectives (Q2)
1. Real-time collaboration in dashboard editing (avoid conflicts, latency < 200ms).
2. AI-assisted insights: highlight anomalies or summarize dashboards in natural language.
3. Observability: standardized tracing + metrics across Next.js/Node services.
4. Testing: increase E2E coverage for critical flows (sign-in, dashboard share, filter application).
5. Security: container image vulnerability scanning in CI before release.

## Constraints & Preferences
- Language/Framework affinity: TypeScript/Node, compatible with Next.js ecosystem; Python acceptable for microservices; Go accepted for CI tools.
- Licensing: Prefer MIT/Apache-2.0/BSD. Avoid GPL/AGPL/LGPL for core dependencies (legal/commercial compatibility).
- Security: No unreviewed code execution. External API usage must be opt-in with explicit approvals and safe defaults.
- Operational: Keep overhead low; avoid heavy server requirements when a client-side solution suffices.

## Selection Criteria for Trending Repos
- Clear fit with one or more Q2 objectives (collaboration, AI, observability, testing, security).
- Compatible license (MIT/Apache-2.0/BSD).
- Active maintenance, good documentation, and practical integration path.
- Minimal risky side effects by default (prefer read-only or configurable network behavior).
- Aligns with existing stack (TypeScript/Node for app code; Go tools acceptable for CI).

## Known Gaps and Opportunities
- CRDT-based collaboration layer for shared edits and comments.
- LLM orchestration for summarizing dashboards (provider-agnostic, privacy-aware).
- Distributed tracing and metrics standardization for Next.js SSR/Edge + Node backend.
- Browser-based E2E testing integrated with GitHub Actions and PR gating.
- Container scanning gate in CI to block high-severity CVEs.

## Evaluation Notes
- Treat “deep-dives” as proposed plans only. Do not clone or execute external code.
- Favor libraries/tools with well-defined security posture and opt-in network behavior.
- Prepare pre-install security scanning steps (exec/network/filesystem/sensitive/domains) before any code is touched.
- Use temporary tooling acquisition with default uninstall/cleanup after evaluation (no permanent install unless approved).