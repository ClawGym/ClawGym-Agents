# Project Demo

A living schema for the end-to-end demo effort across data ingest, processing, alerting, and reporting. Track goals, decisions, risks, and interfaces.

## Overview
The demo showcases a full data pipeline:
- Source ingestion from CSV and JSON feeds
- Transformation with validation and enrichment
- Alerting for anomalies with email and Slack
- Dashboard reporting with daily and weekly summaries
Success is defined as a stable run for three consecutive days with zero P1 issues.

## Milestones
1. Architecture approval
2. Data ingestion ready
3. Transformation rules validated
4. Alerting tuned to reduce false positives
5. Dashboard MVP complete
6. End-to-end dry run with stakeholders
7. Final public demo

### Current Status
- Ingestion: stable for main feeds; backup feed flaky
- Transformation: 95% rule coverage; edge-case handling pending
- Alerting: false positives dropped from 18/day to 3/day
- Dashboard: MVP ready; theming pass planned
- Risk: timeline pressure; team bandwidth thin this week

## Decisions
- Use LanceDB for vector index of schema notes
- Keep alerts in email + Slack for visibility
- Defer multi-tenant support until after demo
- Record all remediation steps in runbook

### Interfaces
- Ingest: S3 bucket (csv/), API (json)
- Transform: Python jobs with configurable rulesets
- Alert: webhooks + SMTP
- Report: dashboards served via internal URL, password-protected

## Runbook Excerpts
If ingestion fails:
- Retry 3 times with exponential backoff
- If still failing, raise P1 and switch to cached snapshot
Transformation anomalies:
- Log detailed record diffs
- Tag with incident ID for traceability
Alert storms:
- Apply temporary dampening rule (max 3/minute)
- Notify on-call to review patterns

### Stakeholders
- PM: Helen — scope and timeline
- Tech Lead: Arun — architecture and quality
- Ops: Jamie — on-call rotation and runbooks
- Design: Priya — dashboard UX and theming

## Risks and Mitigations
- Risk: Backup data feed unreliable → Mitigation: nightly prefetch to cache
- Risk: Demo hardware variance → Mitigation: containerize and test on target
- Risk: Alert fatigue → Mitigation: maintain dampening and severity thresholds

### Notes
Keep all facts brief and actionable. Weekly REM updates will append summarized facts here.