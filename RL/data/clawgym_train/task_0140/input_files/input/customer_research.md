# Customer Research — LogLamp Beta

This document summarizes interviews and observations with our early users. Roles include Backend Engineers and SRE Managers at mid-size SaaS companies (50–500 employees).

## Team Profiles
- Company A (SaaS, ~220 employees): 10 backend engineers, 3 SREs, EKS on AWS
- Company B (Fintech, ~380 employees): 14 backend engineers, 5 SREs, GKE; strict compliance requirements
- Company C (B2B marketplace, ~120 employees): 8 backend engineers, 2 SREs, AKS

## Key Themes
- Correlation-first: users want to move from a single log line to the full trace and Kubernetes context immediately
- Structured logging is widespread, but parsing and schema drift cause troubleshooting friction
- SLI/SLO literacy is rising; teams want SLO-aware alerts to cut noise and align with user impact
- Time to value must be fast (<30 minutes) or tools get deprioritized
- Governance matters for growing teams: audit trails, compliance exports, and RBAC are requested by SRE leadership

## Interview Quotes
> During a Sev2 incident, I don’t have time to sift through unstructured logs. If LogLamp can auto-parse structured logging and correlate with OpenTelemetry traces in Kubernetes, we’re in.

> The killer feature for us is clicking from a 5xx log to the exact trace and seeing which deployment rolled out in the last 10 minutes.

> I want to define SLIs/SLOs per service and get burn-rate alerts that are meaningful. We had to mute half our alerts last quarter.

> If the Helm install gets me from zero to first correlated trace in under 15 minutes, that’s a yes from our team.

> Our auditors require 90-day retention and clear audit logs of who accessed what. Compliance reporting can’t be an afterthought.

> We pass JSON logs everywhere. Please keep the field names searchable without writing regex. Schema drift is real.

> I need a simple way to share a timeline of an incident that combines logs, traces, and deploys for a postmortem.

> We’re on-call with 8 backend engineers rotating weekly. Anything that reduces alert noise without missing SLO violations pays for itself.

> Show me SLO health per service at a glance and let me break down by namespace. If that exists, prioritization becomes straightforward.

> K8s-native context is table stakes. If I can’t filter by namespace/pod/deployment quickly, the tool slows us down.

## Observations
- Teams already emit OpenTelemetry traces for top services; logs are JSON with occasional key=value formats
- Kubernetes is the standard deployment substrate; Helm is the preferred installation path
- Alerting integrations with Slack/PagerDuty are must-haves
- SRE managers care deeply about SLIs/SLOs rollups, auditability, and compliance-ready exports
- Backend engineers judge by speed of search, clarity of correlation, and how quickly they can get to root cause

## Jobs To Be Done (JTBD) Summaries
- When a production error rate spikes, help me navigate from symptom to cause across logs, traces, and Kubernetes deployment context within minutes.
- When I set up service-level objectives, help me pick sensible SLIs/SLOs, enable burn-rate alerts, and avoid alert fatigue.
- When auditors ask for evidence, help me export audit logs and access reports that pass compliance checks.