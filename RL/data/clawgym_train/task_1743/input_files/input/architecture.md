# System Architecture Overview

Product: Multi-tenant B2B SaaS for subscription analytics and revenue operations.

Customers/Scale:
- ~500 paying tenants, ~14K monthly active end users
- Peak traffic: ~1,800 RPS to public API
- Seasonal spikes around month-end close

Tech Stack:
- Frontend: React 18 + Next.js 13 (TypeScript)
- Backend: Node.js 16, Express monolithic REST API (110K LOC)
- Data: PostgreSQL 13 (single shared schema, row-level tenant scoping), Redis 6 for caching/queues
- Background jobs: Bull (Redis-backed)
- Batch ETL: Node workers on cron + ad-hoc scripts
- Messaging: None (HTTP and Redis queues only)
- Infra: AWS (EC2 for app nodes, RDS Postgres, S3 for asset storage, CloudFront CDN)
- Observability: CloudWatch metrics/logs + ad-hoc JSON logs; no distributed tracing; spotty alerting
- Deployment: Manual PM2 restarts on 3 EC2 instances (blue/green not implemented); partial bash scripts; no infrastructure-as-code
- Auth: Auth0 (per-tenant), JWT access tokens

Codebase Size (approx 180K LOC total):
- Backend (Express API + workers): ~110K
- Frontend (Next.js): ~60K
- Internal scripts + infra glue: ~10K

Key Architectural Notes:
- Monolith with tight coupling between modules (billing, reporting, ingestion)
- Shared Postgres schema; heavy reliance on cross-module tables and triggers
- Significant business logic in controller layers; anemic service layer pattern
- No formal bounded contexts; work-in-progress “modularization” branch stalled 3 months ago
- Read-heavy endpoints with occasional N+1 query patterns; slow report generation under load
- Memory pressure during batch jobs due to large in-memory transforms

Testing & Quality:
- Unit test coverage: backend ~28%, frontend ~20%
- No integration tests; e2e (Cypress) only on nightly, frequently flaky (~30% failures)
- Linting partially enforced; inconsistent code style
- 290 production dependencies; 14 are ≥1 major version behind; 3 deprecated with known security advisories

Operations:
- Deployments are manual and error-prone; inconsistent pre-deploy checks
- No canary/blue-green; rollbacks are manual and slow
- Monitoring relies on CloudWatch with basic CPU/memory alarms; limited application-level SLOs
- No synthetic uptime checks; no distributed tracing; limited log correlation across services

Performance Hotspots (observed):
- N+1 ORM queries in Reporting API during peak usage
- Memory leak in ingestion worker causing PM2 restarts under sustained load
- Suboptimal Postgres indices for time-partitioned tables (reports and events)

Business Constraints/Goals:
- 99.9% monthly uptime target
- Time-to-restore under 30 minutes for SEV-1
- Maintain new feature cadence: 2 major features per quarter

Recent Incident Themes (see incidents.jsonl for details):
- Memory leak + no autoscaling (outage, revenue loss)
- Manual deploy rollback due to config drift
- Security exposure from deprecated dependency
- Data inconsistency traced to shared DB and missing integration tests
- Checkout performance regression from N+1 queries

Assumptions relevant to audit:
- Two-week sprints, 12 engineers (see team.json)
- Loaded engineering cost provided in team.json for cost modeling
- Current debt drag estimated at ~25–30% of velocity based on observed incidents and QA backlog