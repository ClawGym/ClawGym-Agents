# Data Retention Policy

This document establishes the rules for data retention across all systems and services operated by the organization.

## Purpose

We define data retention periods to balance operational needs, legal obligations, and privacy expectations.

Definition: Data Retention - The practice of storing data only as long as it is needed for its stated purpose and legal basis.
Definition: PII - Personally identifiable information such as a person's name, email address, phone number, or device identifier.
Definition: Purpose Limitation - Collect data only for specified, explicit, and legitimate purposes.

## Legal Bases and Standards

Under GDPR, data retention must be limited to what is necessary for the purposes identified.
To comply with GDPR and CCPA, the company maintains documented retention schedules and review procedures.
When handling PII, retention periods are tied to the minimal operational window and will be reviewed annually.

## Scope

This policy applies to production databases, file stores, analytics warehouses, and log archives, with special rules for PII.

## Retention Schedules

- Application data (non-PII): Retain for 2 years, then archive for 1 additional year before deletion.
- PII in customer accounts: Retain for the lifetime of the contract plus 90 days for closure processing, then delete.
- Backups containing PII: Retain for 35 days on a rolling basis; backups older than 35 days are purged.
- Security logs: Retain for 90 days to support investigations, per our GDPR-aligned data retention control.
- Audit logs involving access to PII: Retain for 1 year to support compliance reporting and incident response.

## Minimization and Deletion

We practice data minimization and prompt deletion of PII when no longer needed.
Automated deletion jobs enforce data retention schedules and produce reports for audit.
Manual exceptions to data retention require approval by the Data Protection Officer and must cite a legal basis under GDPR or CCPA.

## Cross-Border Considerations

Where applicable, cross-border transfers must meet GDPR adequacy or appropriate safeguards, independent of data retention periods.

## Roles and Responsibilities

- Data Owners: Define data retention periods based on purpose and legal basis.
- Engineering: Implement technical controls that enforce data retention and deletion.
- Security: Validate that data retention controls are effective and aligned to GDPR and CCPA requirements.
- Legal: Advise on regulatory changes that may affect data retention.

## Review and Updates

This policy is reviewed at least annually or when GDPR, CCPA, or other privacy laws are updated.
Changes to retention periods must be documented and communicated to system owners.

## Exceptions

Any exception that extends data retention beyond standard timelines must be time-bound and justified.
Exceptions for litigation holds override standard data retention until the hold is released.

## References

- GDPR Article 5(1)(e) on storage limitation and data retention
- CCPA guidance on retention disclosure and deletion rights
- Internal SOP: Automated Deletion and Retention Verification

End of policy.