# Built-In Memory Snapshot

Captured: 2026-03-08
Owner: Jordan Lee

## Preferences
- Weekly planning cadence: Friday 4pm
- Find method preference: both (navigate via indices + grep)
- Decision logging: Track key choices in Decisions (technical/business/personal) with revisit dates
- Communication: Prefer concise weekly status updates with clear next steps
- Security: Do not store secrets; redact tokens and credentials

## Key Decisions
- 2026-03-01 — Database choice for Helios: Chose Postgres for analytics due to JSONB, lower ops, and strong ecosystem. Revisit at 50M events/day or by 2026-06-01.
- 2026-02-10 — Standup time: Keep daily standup at 10:30am ET (15 minutes).
- 2026-02-20 — Experiment review: Move growth experiment readouts to Tuesdays.

## Contacts
- Alice Kim — PM at Lumen Labs (Helios Launch partner)
- Ravi Patel — Data Engineer (pipelines and ETL)

## Notes
- Keep indices under 100 entries; split active vs archived when needed.
- Archive completed projects quarterly.