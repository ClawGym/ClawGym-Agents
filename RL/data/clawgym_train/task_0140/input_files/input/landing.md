# LogLamp — Light Up Production, Fast

Developer-first observability that unifies logs, traces, and metrics with Kubernetes context so you can find root causes in minutes, not hours.

- OpenTelemetry-native ingestion
- Structured logging parsed automatically
- SLO-aware alerts that reduce noise
- Kubernetes context out of the box

## The Hook
Paste one Helm command, ship OpenTelemetry traces and structured logs, get correlated insights and SLO-aware alerts in under 15 minutes.

## Why Teams Choose LogLamp
- Correlate everything: Every log line links to its trace, span, and Kubernetes deployment
- Ship faster with confidence: SLO burn-rate alerts keyed to real user impact (SLIs/SLOs)
- Cut noise: Fewer, smarter alerts routed to the right on-call
- Designed for developers: Search, pivot, and share timelines that tell the story

## How It Works
1) Install the Helm chart on your Kubernetes cluster
2) Send traces/metrics via OpenTelemetry; logs flow from the DaemonSet with structured logging parsing
3) Define your first SLO from a template; enable smart alerts; pivot between logs and traces during incidents

## Who It’s For
- Backend engineers owning microservices at mid-size SaaS companies
- SRE managers who need consistent SLIs/SLOs, sane alert policies, and reliable audit reporting

## Time to Value
- Kubernetes + OpenTelemetry users: under 15 minutes to first correlated log/trace
- “First success moment”: pivot from an error log to its trace and deployment with a single click

## Key Capabilities
- Structured logging parsing and schema inference
- OpenTelemetry (OTLP) receiver; service maps and trace explorer
- Kubernetes-native enrichment (namespace, pod, deployment)
- SLO templates, burn-rate alerts, and service-level dashboards
- RBAC, immutable audit logs (enterprise), and compliance-ready exports

## Integrations
- Alerts: Slack, PagerDuty, Opsgenie, Email
- Issue tracking: Jira, Linear
- Clouds: AWS/GCP/Azure managed Kubernetes

## Call to Action
Try LogLamp today. Install via Helm and see correlated logs and traces in minutes.