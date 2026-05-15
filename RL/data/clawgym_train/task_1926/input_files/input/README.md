# LiteTrace — Product Overview

Tagline: “Faster distributed tracing without the yak-shave”

## Problem
Modern microservices make understanding request flow and performance regressions hard. Teams struggle with:
- Long setup time and “yak-shaving” to get distributed tracing working (agents, collectors, dashboards, pipelines).
- Heavy agents and vendor lock-in that add CPU/memory overhead and surprise costs.
- Gaps in coverage from missed context propagation and inconsistent instrumentation.
- Sampling strategies that drop the exact spikes/outliers engineers care about.
- Siloed tooling where traces, logs, and metrics don’t align with the developer workflow.

## Solution
LiteTrace is a developer-first tracing toolkit that gets you from “install” to “first actionable trace” in minutes. It integrates directly with your app framework, ships via a lightweight OTLP gateway, and uses Adaptive Burst Sampling to capture the spikes that matter without blowing your budget. It’s compatible with OpenTelemetry and exports to Jaeger, Zipkin, Grafana Tempo, and common APMs.

- Time-to-first-trace: < 10 minutes (no yak-shave).
- Lightweight: < 2% CPU overhead in typical microservice workloads.
- Compatible: Works with OpenTelemetry SDKs and collectors; OTLP everywhere.
- Developer workflow native: CLI, CI guardrails, PR annotations for latency regressions.

## Ideal Customer Profile (ICP)
- Backend engineers, SREs, and platform teams at startups and mid‑market companies (10–500 engineers).
- Environments: Kubernetes, serverless, or VM-based microservices.
- Languages/frameworks: Node.js (Express/Fastify/Nest), Go (net/http, Gin), Python (FastAPI/Flask), Java (Spring) coming soon.

## Key Features
- Auto-Instrumentation:
  - Node.js, Go, and Python starters with zero/low-code setup.
  - Context propagation fixes for common async/task queue patterns.
- Adaptive Burst Sampling:
  - Baseline 1–5% with automatic spike capture when error rate/latency p95 increases.
  - Keeps costs predictable while retaining the interesting outliers.
- Lightweight OTLP Gateway:
  - Deploy as a sidecar or cluster service; forwards to Jaeger, Zipkin, Tempo, or vendors (Datadog, New Relic, Honeycomb, Elastic).
- Developer UX:
  - `litetrace` CLI: local trace tail, “what changed?” diff, and flamegraph snapshots.
  - CI checks: fail PRs when latency budgets or error budgets regress beyond thresholds.
- Privacy & Security:
  - On-gateway PII redaction and field allow/deny lists.
  - Token-free local dev; service account support in prod.
- “Shadow Mode”:
  - Run tracing disabled by default and auto-enable for a subset of requests to validate impact before full rollout.

## Differentiation
- Compared to Jaeger/Zipkin (OSS backends): LiteTrace focuses on install time, developer ergonomics, and adaptive sampling out-of-the-box. Use LiteTrace gateway + your existing Jaeger UI if you prefer.
- Compared to Datadog/New Relic/Honeycomb/Lightstep/Sentry Performance: Vendor products are powerful but can be heavy, expensive, and require agent sprawl. LiteTrace is lightweight, open formats first, and cost-aware.
- Compared to plain OpenTelemetry Collector: OTel is the standard plumbing; LiteTrace adds Adaptive Burst Sampling, developer tooling (CLI/CI), and a fast-path install that avoids yak-shaving.

## What Success Looks Like
- 30–60% faster incident triage (fewer “can’t reproduce” mysteries).
- Fewer flameouts on peak traffic: catch and keep traces during spikes.
- Reduced tracing infra spend while keeping signals that matter.

## Quick Start (Example: Node.js)
1. Install package: `npm i @litetrace/node`
2. Initialize early in your app:
   ```js
   require('@litetrace/node').init({ serviceName: 'api', otlpEndpoint: process.env.OTLP_ENDPOINT });
   ```
3. Deploy LiteTrace Gateway (Helm or docker-compose).
4. Verify: `litetrace tail` to see live spans locally.
5. Export to your chosen backend (Jaeger, Zipkin, Tempo, or vendor APM).

## Roadmap Highlights
- Java (Spring) and Ruby (Rails) auto-instrumentation.
- Anomaly summaries in PRs and Slack notifications.
- eBPF-assisted context hints (opt-in).

## Messaging & Constraints (see posting-rules.md)
- Value-first responses (80% help / 20% product).
- Always disclose builder status: “disclaimer: I’m the developer.”
- No astroturfing or vote-begging. Respect community rules.

## References
Common alternatives in this space include Jaeger, Zipkin, Datadog APM, New Relic APM, Honeycomb, Lightstep, Sentry Performance, Grafana Tempo, Elastic APM, and OpenTelemetry Collector.

—  
Product: LiteTrace  
Tagline: “Faster distributed tracing without the yak-shave”