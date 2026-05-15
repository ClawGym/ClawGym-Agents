# Privacy Guidelines — Baseline Principles

Purpose
- Provide guardrails for how we learn from, store, and act on documentation that may reference sensitive processes or fields.

Core Principles
- Data minimization: Collect and retain only what is required for the task.
- Least privilege: Use the least-sensitive channel capable of completing the task.
- Purpose limitation: Do not repurpose collected data without explicit justification.
- Locality: Store learned data within the local workspace unless otherwise required.

Handling Secrets and Sensitive Data
- Do not log sensitive environment variables or API keys.
- Never copy raw secrets, long-lived tokens, or private keys into memory files, operational rules, or commit history.
- Redact or hash personal identifiers and confidential values when writing diagnostic notes.
- Avoid echoing Authorization headers, session cookies, or secret-bearing URLs in logs or error messages.
- Prefer short-lived, capability-scoped tokens for webhooks or API calls.

Webhooks and External Channels
- Require HTTPS for webhook endpoints.
- Prefer signed payloads (HMAC or asymmetric signatures). Validate signatures before processing.
- Rate-limit and throttle unauthenticated endpoints where possible.
- Do not include PII unless strictly necessary; if included, encrypt at rest and in transit.

Access and Retention
- Restrict access to memory and rules files to the workspace runtime.
- Establish a retention policy: rotate or purge old tokens, stale routing data, and outdated card copies.
- On decommission or handoff, securely delete sensitive artifacts.

Incident Response
- If sensitive data is accidentally captured, immediately redact, rotate impacted tokens, and document the remediation.
- Notify relevant stakeholders according to policy.

Compatibility Notes
- Follow the current specification versions referenced by local documentation.
- Verify compatibility with the current OpenClaw version before integrating new patterns.