# Backup Policy, Retention, and Scheduling

This document covers backup strategy, retention periods, and operational procedures for data protection.

## Backup Schedule
We maintain a backup schedule for production databases: nightly incrementals at 02:00 UTC and weekly full backups on Sundays.
The backup schedule covers all regions and services, including object storage, metadata stores, and search indices.
Review the backup schedule quarterly and after any major architecture change.

## Retention
- Incremental backups retained for 14 days.
- Full backups retained for 6 months.
- Critical compliance datasets retained for 7 years.

## Testing and Restore
- Perform quarterly restore drills from randomly selected backups.
- Validate RTO and RPO against documented targets.
- Keep runbooks updated with restore steps and access controls.

## Security and Access
- Backups are encrypted at rest and in transit.
- Access to backup repositories is restricted to the on-call and data engineering teams.