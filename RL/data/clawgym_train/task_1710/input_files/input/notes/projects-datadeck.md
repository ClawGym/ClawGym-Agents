# Project: DataDeck

Overview
- DataDeck is a lightweight SaaS project for aggregating and visualizing team metrics and KPIs.

Status
- completed

Key Attributes
- type: SaaS
- features: 59
- url: https://datadeck-preview.vercel.app
- primary users: engineering managers and tech leads
- hosting: Vercel (Next.js front end), serverless API
- data sources: GitHub, Jira, Linear, custom webhooks
- persistence: Postgres (managed), nightly backups at 03:00 UTC
- security: SSO (Okta) and role-based access control
- success criteria: weekly active users > 50, dashboard load < 1.2s p95

Notes
- Post-launch focus is usage instrumentation and content library growth.
- Consider tagging dashboards by team for better discoverability.