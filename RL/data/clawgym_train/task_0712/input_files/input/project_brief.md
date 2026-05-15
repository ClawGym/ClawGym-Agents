# Internal Engineering Assistant — Project Brief

## Objective
Build a cost-aware AI assistant that supports our engineering org across three phases:
1) Planning: architecture and design decisions for new or evolving services
2) Execution: day-to-day code implementation tasks (functions, tests, small refactors)
3) Review: final code review prior to merge (CI-integrated)

The assistant must balance quality with spend, defaulting to mid-tier models and escalating to frontier only when quality or risk justifies it. Open-source/self-hosted models are considered for privacy-sensitive or predictable-cost workloads.

## Target Users and Languages
- 3 platform teams (backend, web, data), ~35 engineers total
- Primary languages: Python 3.12, TypeScript/Node, some Go
- Repo size: medium; monorepo (services + packages) with typical PR diffs of 500–1500 LOC

## Workflows by Phase
- Planning (Architecture/Design):
  - Inputs: RFCs (8–12 pages), service dependency maps, API boundaries, SLOs
  - Outputs: Design alternatives with tradeoffs, dependency risks, suggested interfaces
  - Typical context assembled: ~12,000 tokens in; ~2,000 tokens out
  - Request volume: ~20/day
  - Notes: Occasionally large context when stitching multiple docs (up to ~150,000 tokens)

- Execution (Day-to-Day Implementation):
  - Inputs: task description, code snippets, interfaces, tests to extend
  - Outputs: code blocks, tests, small refactor plans
  - Typical context: ~3,000 tokens in; ~6,000 tokens out (code-heavy output)
  - Request volume: ~200/day (bursty during sprints)
  - Notes: Interactive preference in IDE, but background batch jobs allowed for scaffolding

- Review (Final Code Review in CI):
  - Inputs: PR diffs (500–1500 LOC), test results, lints, style rules
  - Outputs: structured review comments, potential bug/async edge-case notes
  - Typical context: ~8,000 tokens in; ~1,200 tokens out
  - Request volume: ~40/day
  - Notes: Accuracy and thoroughness matter more than raw speed

## Performance and Latency Tolerance (P95)
- Planning: up to 60 seconds acceptable
- Execution: <= 10 seconds preferred for interactive tasks; up to 20 seconds for background
- Review: up to 120 seconds acceptable in CI

## Privacy & Compliance
- Proprietary code and business logic; no PII in prompts by default
- Require vendor DPAs and US/EU data residency options for hosted APIs
- Self-hosted (open-source) required for security audits and PCI-adjacent repos

## Cost & Operations
- Budget guidance: see constraints.json (monthly cap and daily soft caps)
- Use batch APIs for non-real-time workloads (e.g., nightly scaffolding or mass small tasks)
- Enable prompt caching to reduce repeated context costs (e.g., shared libraries/RFCs)
- Track cost per request and per merged PR; default mid-tier; escalate only when quality dips
- Context window constraints matter for long RFCs and large diffs; prefer large-context models for Planning and Review when needed

## Success Metrics
- 20–30% reduction in time-to-merge for typical PRs
- Fewer regressions caught late (increase early defect detection by 15%)
- Cost per merged PR monitored and kept within budget envelopes
- Quarterly reassessment of model choices and pricing