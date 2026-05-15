# Rate Limiting

This document describes how the Acme Dev Platform API enforces rate limits, how to read limit headers, and the recommended retry strategy.

---

## Default limits

- Per-token limit: 120 requests per minute (RPM)
- Per-IP soft limit: 600 requests per minute (shared across tokens)
- Bursts: Token bucket with a burst capacity of 20 requests
- Window: Rolling window algorithm for fairness

Enterprise plans may have negotiated limits; contact support to adjust.

---

## Headers

Every response includes rate limit headers:

- X-RateLimit-Limit: The maximum requests per minute allowed for your token
- X-RateLimit-Remaining: How many requests remain in the current window
- X-RateLimit-Reset: UTC epoch seconds when the remaining count resets
- Retry-After: Present when you must wait before retrying (429 responses)

Example:

```
HTTP/1.1 200 OK
X-RateLimit-Limit: 120
X-RateLimit-Remaining: 43
X-RateLimit-Reset: 1737072000
```

On limit exceeded:

```
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
X-RateLimit-Limit: 120
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1737072000
Retry-After: 12
```

Body:
```
{
  "error": "rate_limited",
  "message": "Too many requests; retry after 12 seconds"
}
```

---

## Counting rules

- Each request counts as 1 unit unless otherwise specified.
- Some high-cost endpoints (e.g., /v1/search:semantic) may count as 2 units due to compute usage.
- Long-poll or streaming endpoints are counted when the connection is established.

---

## Retries and backoff

Best practices:
1) Inspect `Retry-After` and wait that many seconds before retrying.
2) Use exponential backoff with jitter for 429 and 503 responses.
3) Batch requests where possible (e.g., /v1/batch/projects).
4) Cache GET responses using ETags to avoid re-fetching.

Simple backoff pseudocode:
- base = 1s; attempt = 0..N
- sleep = min(Retry-After, base * 2^attempt + random_jitter)

---

## Idempotency

For POST endpoints that create resources, provide an Idempotency-Key header to safely retry after a 429:

```
Idempotency-Key: 5a3b1f6e-7c11-4b5f-9c66-9d8c9183d7a0
```

If the previous attempt succeeded but the client did not receive a response, the server returns the original result for the same key.

---

## High-volume strategies

- Use server-side webhooks or async jobs for bulk operations.
- Prefer streaming result sets to reduce pagination churn.
- Compress request payloads where supported.

---

## Exempt and special endpoints

- /v1/status and /v1/health are not rate-limited.
- /v1/auth/* endpoints have higher limits to support authentication flow spikes.
- Abuse detection may temporarily reduce limits for suspicious patterns regardless of plan.

---

## Organization and team limits

When using organization-scoped tokens:
- Limits apply per token and aggregate at the org level to prevent noisy neighbor issues.
- If your org hits the aggregate limit, tokens may simultaneously receive 429 responses.

---

## Testing in sandbox

Sandbox limits are intentionally lower:
- Per-token: 60 RPM
- Burst: 10
- Use this to validate your backoff and retry logic.

---

## Troubleshooting

- Sudden 429s after deployment: Check for accidental infinite loops or missing backoff.
- Limits vary by endpoint: /v1/search:semantic counts as 2 units; check the “Counting rules.”
- Retry-After header missing: Default to exponential backoff with jitter; start at 2 seconds.

---

## Examples

cURL with retry guidance:

```
curl -H "Authorization: Bearer $TOKEN" \
     -H "Idempotency-Key: $(uuidgen)" \
     https://api.acme.dev/v1/search?q=hello
```

If 429 received:
- Parse Retry-After
- Sleep
- Retry with same Idempotency-Key if creating a resource

---

# End of rate limiting documentation