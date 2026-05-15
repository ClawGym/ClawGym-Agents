# Email Outreach Compliance Policy (Audit Rules)

These rules define what we consider compliant for our career-starter outreach list. The audit must check the items below solely against local files.

- R1 Explicit consent: consent_checkbox must be true AND consent_timestamp must be present for a record to be eligible for email outreach.
- R2 Double opt-in: double_opt_in_confirmed must be true for all regions.
- R3 Consent text version: consent_text_version must be present on each record and must match a valid id in consent_texts.json.
- R4 EU age requirement: if region == "EU", the person must be at least 16 years old at the time of consent_timestamp (compute from birthdate).
- R5 Unsubscribe tracking: if unsubscribed == true, unsub_timestamp must be present.
- R6 IP logging: app_config.yaml must have log_ip == true.
- R7 Unengaged retention limit: app_config.yaml must have retention_days_unengaged <= 365.
- R8 Unsubscribe URL: app_config.yaml must include a non-empty unsubscribe_url.
- R9 Code persistence: the signup handler must persist the consent_text_version field when saving consented records.

Severity guidance for record-level findings:
- High: Violations of R1, R2, or R4.
- Medium: Violations of R3.
- Low: Violations of R5.

Configuration/code-level findings should be reported in the audit summary with pass/fail and a short explanation.
