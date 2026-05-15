# Engineering Learnings Notes

These are concise, team-ready learnings captured from recent work. Each bullet is a single learning; category is derived from the section heading.

## Best Practices
- Always set timeouts on outbound HTTP requests (Context: network resilience)
- Validate JSON schemas at service boundaries to fail fast (Context: API ingestion)
- Use feature flags for risky changes and gradual rollouts (Context: release safety)

## Techniques
- Use chunked/streaming uploads for large files to avoid request timeouts (Context: file upload service)
- Use idempotency keys for external POST requests to prevent duplicates on retries (Context: payments/invoices)
- Shadow traffic to new services before cutover to verify parity (Context: migrations)

## API Endpoints
- Respect Retry-After header on 429 responses; backoff with jitter (Context: VendorX /search)
- Stripe-style webhooks may deliver duplicates; verify signature and de-duplicate by event id (Context: webhook consumers)

## Constraints
- Keep background jobs under 10 minutes on our PaaS; long tasks must be chunked or queued (Context: platform limits)
- Max 20 parallel workers per service to protect the DB connection pool (Context: database saturation)

## Error Handling
- Prefer exponential backoff with full jitter on transient errors (Context: rate limits and timeouts)
- Log structured errors with request_id and correlation_id for traceability (Context: observability)