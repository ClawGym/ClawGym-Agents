# HEARTBEAT — Periodic Tasks

Schedule
- 02:00 Daily: backup
- 03:00 Sunday: validate

Guards
- Skip if previous operation still running
- Capture summary output for each run

Observability
- Print counts of files, sizes, and hash summary
- Non-zero exit code on validation failure