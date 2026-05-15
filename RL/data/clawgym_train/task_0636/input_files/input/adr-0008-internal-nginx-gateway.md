# ADR-0008: internal-nginx-gateway

## Status
Accepted

## Context
In early 2024, the platform needed a simple, low-cost inbound gateway to front Kubernetes workloads. The team had deep operational familiarity with Nginx, and the Nginx Ingress Controller was widely used and understood across our clusters. Requirements included TLS termination, basic path-based routing, and compatibility with our existing Helm/GitOps pipeline.

The alternatives considered at the time (Envoy-based gateways and commercial API gateways) introduced additional complexity, licensing questions, or learning curves that did not align with our time-to-market goals.

## Decision
We will standardize on the self-managed Nginx Ingress Controller as our internal API gateway for public and internal HTTP traffic. We will use Ingress resources with annotations and limited Lua plugins to provide basic rate limiting, JWT verification at the edge for public endpoints, and path-based routing to backend services.

## Consequences

### Positive
- Rapid delivery using a familiar and widely documented Nginx stack
- Minimal cost and straightforward Helm-based deployments
- Simple operational model aligned with current team skills

### Negative
- Advanced features (per-tenant rate limiting, mTLS policy management at scale) are not first-class and require custom work
- Configuration drift risk due to various annotations and snippets scattered across repos
- Limited plugin ecosystem alignment for evolving auth and policy needs

### Risks
- Over-reliance on custom Nginx snippets could introduce fragility and increase toil
- As the platform grows, centralized policy enforcement and auditable changes may be difficult to maintain

## Related
- Platform Helm charts (nginx-ingress) in the ops-infra repository
- OTel collector pipeline for Nginx access logs and metrics