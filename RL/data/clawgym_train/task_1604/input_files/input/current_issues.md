# Current Issues and Considerations

## Pain points
- Duplicate lead entries when the same person submits the form multiple times, causing repeated intro emails and double CRM records.
- Manual copying from the web form to CRM is error-prone (missed fields, inconsistent capitalization).
- Weekly client report preparation is repetitive and time-consuming; sometimes reports are sent late due to manual steps.
- Invoices are occasionally not marked as paid promptly after payment capture, leading to confusing reminders.
- Scheduling discovery calls across time zones is inconsistent, and calendar invites sometimes miss the correct time zone.

## Data quality issues
- Invalid or disposable emails (e.g., use of temporary email domains) lead to bounces.
- Incomplete form submissions (missing company or budget_range) reduce lead qualification quality.
- Multiple emails for the same company or person (e.g., john@company.com and j.smith@gmail.com) cause fragmented CRM records.
- UTM parameters are missing or malformed; referrer URLs sometimes contain tracking noise.
- Budget ranges sometimes come in as "Unknown" or free-text outside the allowed set.

## Failure patterns
- Webhook timeouts and retries have led to duplicate processing (same event replayed).
- Stale webhook signing secrets not rotated on time caused signature verification failures.
- Payment currency mismatches (client pays in EUR but invoice expected USD) cause reconciliation flags.
- API rate limits hit during batch operations (e.g., sending multiple follow-ups), causing partial completion.
- Attachment uploads fail when files exceed 10 MB size limit, causing partial onboarding.

## Compliance and privacy considerations
- GDPR/PECR: Only send marketing emails to leads with explicit consent; maintain an audit trail.
- Data minimization: Avoid storing raw PII in logs; use hashed email as deduplication key where possible.
- Honor unsubscribe status; ensure suppression lists are respected across automations.
- Retain evidence of consent (timestamp, IP/country if available) for at least 24 months.
- Prefer US/EU data residency for storage; avoid tools that export data to unknown regions.

## Edge cases observed
- Test submissions using fake emails (e.g., test@example.com) that should be ignored downstream.
- Same person submits via personal and work email within a week; both map to the same company.
- Leads choosing "Other" for project_type with useful details only in the message field.
- Company name missing but website provided; needs enrichment before CRM entry.
- Phone numbers not in E.164 format; downstream validation fails or formatting breaks calendar invites.
- Daylight saving time changes causing off-by-one-hour meeting times for UK/US clients.
- Legacy CSV imports introduce stray quotes/encoding issues that confuse parsers.