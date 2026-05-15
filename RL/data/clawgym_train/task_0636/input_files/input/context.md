# Internal Developer Platform — Context and Constraints

Initiative: Internal Developer Platform (IDP) for product and internal services
Codename: Atlas
Environment: Kubernetes (EKS in us-east-1, GKE in europe-west1), multi-tenant

## Current State
- 180+ microservices (Go, Java, Node.js)
- Traffic mix: ~85% service-to-service (internal), ~15% public APIs (behind CDN)
- Ingress: Nginx Ingress Controller (self-managed) with a small set of Lua plugins and custom snippets
- Observability: OpenTelemetry (tracing), Prometheus + Tempo/Jaeger, Loki for logs
- Messaging: Kafka for audit events, analytics pipelines, and some async workflows

## Drivers and Constraints
- Security/compliance (2026 Zero Trust update):
  - Mandatory mTLS for all internal service-to-service traffic
  - JWT auth with audience and scope checks for public APIs
  - Per-tenant rate limits and quotas with auditable policy changes
  - Centralized audit logs with request/response metadata retention (90 days)
- SLOs:
  - Inter-service p95 latency < 50ms; p99 < 150ms
  - Availability ≥ 99.95% for core platform services
- Operations:
  - Ingress maintenance staffed at ~0.5 FTE; custom Nginx config sprawl has become brittle
  - Desire for fully declarative, GitOps-managed configuration (no hand-edited ConfigMaps/snippets)
  - Canary and shadow traffic support required for safe migrations
- Client realities:
  - Some partner networks strip or rewrite non-standard/custom headers
  - Edge/CDN caching is easier with path-based versioning (URL segments)
  - Mobile clients and long-lived partner integrations need explicit, stable URIs (slow upgrade cycles)
- Technology baseline:
  - Two teams piloted gRPC internally; saw 25–35% latency improvements vs REST+JSON for similar payloads
  - Browser/client compatibility requires REST/JSON at the edge (gRPC not suitable for browser-only clients)
  - Kafka is well adopted for async, at-least-once event flows; not used for low-latency request/response
- Gaps with current Nginx ingress:
  - No first-class mTLS policy management across namespaces
  - Per-tenant rate limiting and JWT policies are inconsistent and hard to audit
  - Limited plugin ecosystem fit; hard to evolve without maintaining custom patches
  - Configuration drift and reloads cause occasional brownouts during peak traffic
- Multi-environment requirements:
  - Dev/stage/prod parity, region-aware routing, and gradual rollouts
  - Consistent policy enforcement and telemetry across clusters

## Decision Contexts to Address
1. Edge Gateway Strategy:
   - Evaluate deprecating self-managed Nginx ingress in favor of a gateway with richer policy, plugin, and mTLS support (e.g., Kong Gateway or Envoy Gateway) that fits GitOps and zero trust.
2. API Versioning:
   - Balance clarity and cacheability for public APIs with internal evolution needs.
   - Consider that some proxies strip custom headers and CDNs cache by URL path easily.
3. Inter-Service Communication:
   - Choose a standard for synchronous service-to-service calls under tight latency SLOs.
   - Account for polyglot teams, contract-first development, and OpenTelemetry instrumentation.
   - Async (Kafka) remains for decoupled event flows; not the default for request/response.

## Non-Goals
- Replacing Kafka for events
- Standardizing browser-facing gRPC (will remain REST/JSON through the edge)
- Making breaking API changes without clear versioning and deprecation policy

## Success Criteria
- mTLS + auth policies are centrally managed, auditable, and consistent
- Reduced operational toil on ingress/gateway (≤ 0.25 FTE post-migration)
- Clear API versioning visible to external clients and CDN-friendly
- Internal services meet latency SLOs with typed contracts and good observability
- Clean GitOps workflow for gateway and service policies across environments and regions