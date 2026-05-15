# LogLamp — Developer-First Observability for Fast Incident Triage

LogLamp helps engineering teams find and fix production issues faster by unifying structured logging, traces, and metrics with Kubernetes context out of the box. It is OpenTelemetry-native, SLO-aware, and built for developer workflows.

## Positioning
- Category: Observability and log intelligence for modern SaaS applications
- Primary audience: Backend Engineers at mid-size SaaS companies (50–500 employees, 5–20 engineers per product area)
- Secondary audience: SRE Managers responsible for reliability, SLIs/SLOs, and alert strategy
- Key differentiator: Correlation-first design — every log line is enriched with trace, span, pod, and deployment metadata so developers jump directly from symptom to root cause

## Core Capabilities
- OpenTelemetry-native ingestion (OTLP HTTP/gRPC) for traces and metrics
- Automatic parsing and enrichment for structured logging (JSON, key=value) with dynamic schema inference
- Kubernetes-aware log collection and enrichment (namespace, pod, container, node, labels, deployment, revision, image)
- Built-in SLO templates and burn-rate alerts tied to SLIs/SLOs
- Search, pivot, and correlation: jump between logs ↔ traces ↔ metrics in a single click using correlation IDs
- Live tail with production-safe filters and privacy guards
- Cost controls: retention tiers, dynamic sampling for high-volume services
- Governance features: role-based access control, immutable audit logs (enterprise), redaction policies for PII, compliance-ready export

## Key Integrations
- Languages: Go, Java, Node.js, Python, Rust via OpenTelemetry SDKs
- Ingest: Filebeat/Fluent Bit compatible, OTLP receiver
- Cloud: AWS/EKS, GCP/GKE, Azure/AKS; on-prem Kubernetes supported
- Alerts: PagerDuty, Slack, Opsgenie, Email
- Ticketing: Jira, Linear (via webhooks)

## Installation & Setup
- Kubernetes Helm chart
  - helm repo add loglamp https://charts.loglamp.dev
  - helm upgrade --install loglamp loglamp/loglamp -n observability --create-namespace
- Agents:
  - Logs: DaemonSet collector ships container stdout/stderr with structured logging support
  - Traces/Metrics: OTLP receiver, OpenTelemetry Collector distribution included
- Minimal required config:
  - Cluster name, environment (prod/staging)
  - Service name convention (service.namespace)
  - SLO template selection (e.g., HTTP availability, latency p95)
- Time to value: under 15 minutes for Kubernetes users sending OpenTelemetry traces and structured logs

## First Success Moment
- Within minutes, users can:
  1) Search a production error by service name
  2) Click a trace_id to pivot from logs to trace view
  3) See correlated Kubernetes deployment and recent release notes
  4) Confirm or rule out a candidate root cause

## Target Users
- Primary: Backend Engineer at mid-size SaaS
  - Responsibilities: building services, debugging incidents, performance improvements, release validation
  - Context: on-call rotations, ownership of 3–8 microservices, high pressure during incidents
- Secondary: SRE Manager
  - Responsibilities: reliability program, SLI/SLO design, alert policy, incident management, compliance reporting and audit readiness
  - Context: cross-team visibility, budget accountability, noise reduction, governance

## Top Use Cases
1) Incident triage: correlate spikes in 5xx rates with code changes, Kubernetes rollouts, and error logs
2) Release validation: watch p95 latency and error budget burn during and after deploys
3) Alert quality: SLO-burn alerts that reduce noise while catching real regressions
4) Compliance/Governance: retention policies, audit reports for access and configuration changes

## SLOs & Alerts
- SLIs/SLOs:
  - HTTP availability, latency (p50/p95/p99), error rate, queue depth, saturation
- Alert strategies:
  - Multi-window, multi-burn-rate alerts mapped to SLOs
  - Routing by service, team, environment
  - Suppression during known maintenance windows

## Data Model & Correlation
- Enrichment keys: trace_id, span_id, k8s.namespace, k8s.pod, k8s.container, deployment, git.commit, release.version
- Structure-first ingestion: detect JSON logs, parse fields into searchable attributes
- Pivot actions:
  - Logs → Trace for selected event
  - Trace → Logs for the same time window and correlation ID
  - Logs/Traces → Kubernetes rollout timeline for the same service

## Security & Compliance (Enterprise)
- Role-based access controls with service-level scoping
- Immutable audit log for configuration and access events
- Field-level redaction for PII and secrets
- Export and retention policies aligned with compliance standards

## Pricing & Packaging
- Team: up to 50 GB/day, 7-day hot retention, SLO templates, Slack alerts
- Growth: up to 300 GB/day, 14-day hot + 30-day warm retention, PagerDuty/Opsgenie, audit export
- Enterprise: custom ingestion limits, 90+ day retention, fine-grained RBAC, compliance & audit features, SSO/SAML

---

LogLamp is designed so developers can move from symptom to cause in seconds, with OpenTelemetry, structured logging, Kubernetes context, and SLI/SLO-aware alerts built in.