# Known Risks and Dependencies — BrightTrail Commerce LLC

1) Data access and credentials
- Risk: Delays obtaining read-only credentials, API keys, and network access could block early phases.
- Mitigation: Begin security reviews and access provisioning in parallel with SOW; provide a checklist of required scopes and endpoints in week 1.

2) PCI/PCI-DSS scope control
- Risk: Changes that unintentionally touch cardholder data flows could expand PCI scope (PCI-DSS SAQ A posture at risk).
- Mitigation: Strictly segregate payment data; use tokenized fields only; confirm data maps with Finance and Security before cutover.

3) Legacy script fragility
- Risk: Limited knowledge of existing Lambda/cron scripts may complicate reverse engineering and parity testing.
- Mitigation: Time-box discovery; prioritize must-have connectors; establish acceptance tests around known reports.

4) Reporting SLO breach during cutover
- Risk: Daily Finance reports could miss the 8:30am ET deadline during migration windows.
- Mitigation: Staged cutover with rollback; dual-run validation period; freeze changes during month-end close.

5) Third-party connector or API limits
- Risk: Rate limits or connector instability may cause ingestion failures.
- Mitigation: Implement backoff/retry, incremental syncs, and proactive monitoring; coordinate with vendors if sustained limits appear.

6) Resource availability and change windows
- Risk: Limited internal reviewer bandwidth (Priya’s team) or tight Tues–Thurs change windows could slow approvals.
- Mitigation: Pre-schedule reviews; maintain weekly cadence; escalate early to Marco for unblock.

7) Cost surprises
- Risk: Increased Snowflake consumption or connector fees during dual-run testing.
- Mitigation: Enable cost monitoring and set budget alerts; schedule load tests in off-peak hours.