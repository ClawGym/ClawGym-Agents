# ROI deep dive kickoff
Date: 2026-04-10

Participants:
- Alex Rivera — FinOps Lead
- Priya Shah — Network Engineering Manager
- Marco Li — Backup Administrator
- Dana Kim — SRE Manager
- Jordan Lee — Security Officer

## Decisions
- Proceed with a small cloud pilot while evaluating on-prem refresh.
- Use production-like workload profiles from last quarter.

## Open Questions
1) What is the realistic monthly egress we should plan for between regions and to end-users?
2) How long do we need to retain weekly full backups and daily incrementals for compliance?
3) Do we need a separate test environment for blue/green deployments, or can we reuse capacity off-hours?

## Notes
- Cost sensitivity to data transfer and backup retention came up repeatedly.
- SRE wants to confirm service limits align with workload peaks.
