# Structured Logging Requirements

## Required Fields
- timestamp (ISO 8601 with UTC offset, e.g., 2026-04-25T09:32:18Z)
- level (error, warn, info, debug)
- service (service name)
- event (short machine-readable string, e.g., "payment_failed")
- requestId (unique per request)
- http.method (GET, POST, etc.)
- http.path (endpoint path only; exclude query parameters unless essential)
- http.status (integer)
- duration_ms (integer, total request duration in milliseconds)

## Optional Fields
- correlationId (cross-service correlation identifier; propagate if present)
- userId (hash or surrogate key; do not log emails or raw identifiers)
- error (object with name, message, and stack truncated to reasonable length)
- meta (object for additional context: feature flag keys, region, shard)

## Formatting
- JSON lines, one object per line.
- UTF-8 encoded.
- Keys use lowerCamelCase for top-level fields; nested objects as needed.
- Avoid high-cardinality labels in keys; prefer values in fields (e.g., do not embed requestId in keys).

## Privacy and Security
- Never log secrets, tokens, session IDs, payment card numbers, or CVV.
- Mask or hash any personal data; log only what is necessary for diagnostics.
- IP addresses should be truncated or anonymized as per policy.
- Redact query parameters that may include PII.
- Follow data retention policy: error logs 90 days, access logs 30 days, debug logs 7 days.

## Reliability
- Logs must be written synchronously on errors and asynchronously on success paths where feasible.
- Include requestId and, if available, correlationId on every log line related to a request.
- Ensure log clocks are synchronized across hosts (NTP or equivalent).

## Example (for reference only)
```json
{"timestamp":"2026-04-25T09:32:18Z","level":"error","service":"payments","event":"payment_failed","requestId":"f9f5a3d7-4f1e-4951-8f7a-2f3d0c9b6d42","correlationId":"6c4b5ab1-7b0e-4b2e-8c0c-9b6c2d1f3a77","userId":"u_3f6c1e9b","http":{"method":"POST","path":"/v1/charge","status":502},"duration_ms":742,"error":{"name":"UpstreamError","message":"processor timeout","stack":"..."},"meta":{"region":"us-east-1","retry":1}}
```