# Feedback Triage Automation — Requirements

Owner: Support Lead (SaaS startup)
Scope: Intake and triage of customer feedback from email and website form into ticketing, with acknowledgements and daily digest.

## Objective
Design a robust, rate-limit-aware automation that:
- Ingests customer feedback from:
  - Email trigger: new_email (e.g., support@company.example)
  - Website form webhook trigger: webhook_ticket (HTTPS POST)
- Classifies messages with an LLM (category, sentiment, urgency)
- Creates or updates tickets in the ticketing platform
- Sends acknowledgements to the user (email reply for new_email, webhook response or follow-up email for website form)
- Aggregates a daily digest for product and success teams (daily_digest)

## Required Deliverables (agent-produced under output/)
1) workflow_blueprint.json — Normalized workflow blueprint named “Feedback Triage Automation” with ordered steps, explicit types, and per-step failure handling. Must include rate limiting guard for LLM and ticketing steps, and handle both new_email and webhook_ticket triggers.
2) agent-card.md — Agent Contact Card with YAML frontmatter (version: "1"), channels (email + webhook with url and method), capabilities (include support_tickets), plus clear routing rules and a “Response time:” line.
3) progress.md — Compact progress log following the disciplined execution loop (Goal, Constraints, Candidate paths, Current action, Evidence, Next move/Stop reason).
4) rate_plan.json — Machine-readable rate limit plan for “openai” and “zendesk” including: limit, windowMs, retry, maxRetries, queueSize, strategy.

## Key Constraints
- Respect API rate limits provided in api_limits.json (openai for classification, zendesk for ticketing).
- Single-purpose steps with explicit on_failure behavior (retry | skip | stop).
- Idempotency: Deduplicate repeated inbound messages (e.g., same Message-ID, same webhook request-id).
- PII handling: Do not persist secrets; redact tokens and credentials from logs.
- Acknowledgement within 5 minutes for inbound email and website submissions (best effort with queueing).
- Classification targets:
  - category: bug | feature_request | billing | question | abuse_or_spam
  - sentiment: positive | neutral | negative
  - urgency: P0 | P1 | P2 | P3 (P0 highest)
- Ticket routing:
  - bug -> Support Tier 2
  - billing -> Billing Ops
  - feature_request -> Product Backlog
  - question -> Support Tier 1
  - abuse_or_spam -> Auto-close or quarantine (no customer acknowledgement)
- Daily digest (daily_digest trigger): Summarize the last 24h by category, top themes, and counts.

## Inputs
- Email trigger: new_email
  - Fields: message_id, from_email, subject, body_text, received_at
- Webhook trigger: webhook_ticket
  - Fields: request_id, email (optional), topic, message, submitted_at, source="website"
- Scheduled trigger: daily_digest
  - Time window: previous 24 hours

## Acceptance Checks
- Workflow includes both triggers named “new_email” and “webhook_ticket”.
- At least one LLM step for classification.
- Steps to create/update tickets and send acknowledgements.
- A rate limit guard step for LLM and ticketing calls (guard or wrapper) with retry/skip logic.
- Daily digest generation and dispatch (email or internal note).

## Minimum Acceptable Result
- A blueprint with ≥7 ordered, single-purpose steps covering:
  - Intake for new_email and webhook_ticket
  - Rate limit guard before LLM classification
  - LLM classification
  - Rate limit guard before ticket API call
  - Ticket create/update
  - Acknowledgement (if not abuse_or_spam)
  - Logging/persistence step (db or task)
  - Digest generation (for daily_digest)
- Clear per-step on_failure behavior.

## Stop Conditions
- All four deliverables compiled, with steps meeting the acceptance criteria and rate-plan aligned to api_limits.json;
- Or, a proven hard blocker (e.g., missing required inputs) explicitly named with evidence.

## Operational Notes
- Idempotency keys:
  - new_email: use message_id
  - webhook_ticket: use request_id
- Acknowledgement templates:
  - Email/Web:
    - Subject: “We’ve received your message (Ref: {{ticket_id}})”
    - Body: “Thanks for contacting us about {{category}}. We created ticket {{ticket_id}}. We’ll follow up soon. If urgent, reply with ‘URGENT’. — Support”
- Spam handling:
  - If category = abuse_or_spam with high confidence, do not send an acknowledgement; mark ticket as quarantined or auto-closed with internal note.

## Non-Functional Requirements
- Observability: Record classification outcome, ticket id, acknowledgement status, and any rate-limit waits.
- Security: Store only necessary metadata; do not persist raw credentials or secrets.
- Timeouts: Treat API timeouts as retryable up to maxRetries in the rate plan.

See api_limits.json for nominal limits and scenarios.csv for test scenarios and triggers.

---