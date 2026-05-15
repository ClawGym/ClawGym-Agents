# Downstream Service Spec: Inventory API

The service communicates with an Inventory downstream at:
- Base URL: http://inventory-service.local
- Key endpoints:
  - GET /items/{id}
  - POST /items

## Common Failure Modes

These failure modes occur frequently and must be handled appropriately.

1) Network Timeouts
- Symptoms: connect/read timeout
- Exceptions: ConnectTimeout, ReadTimeout
- Handling:
  - Retry with exponential backoff + jitter
  - Include correlation ID header (X-Request-ID) on retries

2) Connection Reset / ECONNRESET
- Symptoms: abrupt connection drop during request
- Handling:
  - Retry as transient failure
  - Jittered backoff to avoid thundering herd

3) 429 Too Many Requests (rate limiting)
- Behavior: Downstream may include Retry-After header (seconds)
- Handling:
  - Treat as retryable; respect Retry-After if present (sleep at least that duration)
  - Do not hammer; backoff and jitter

4) 503 Service Unavailable (maintenance/overload)
- Handling:
  - Retry with backoff + jitter
  - Log degraded state with requestId

5) 502 Bad Gateway (upstream error)
- Handling:
  - Retry with backoff + jitter
  - If repeated, circuit breaker should OPEN

6) 500 Internal Server Error (intermittent)
- Handling:
  - Retry as transient with backoff + jitter
  - If persistent, circuit breaker will OPEN

7) 504 Gateway Timeout
- Handling:
  - Retry as transient error

8) 404 Not Found
- Handling:
  - Not retryable; translate to a NotFoundError (404)
  - Provide safe message in envelope

9) 422 Unprocessable Entity (invalid ID or payload)
- Handling:
  - Not retryable; translate to ValidationError (422)
  - Include field-level errors in details if available

10) 401 Unauthorized / 403 Forbidden
- Handling:
  - Not retryable; propagate failure
  - Return correct status codes

11) Malformed JSON Response
- Symptoms: Downstream returns non-JSON body for JSON endpoint
- Handling:
  - Treat as 502 Bad Gateway (operational)
  - Do not expose raw downstream body in client response
  - Log parse error with requestId and downstream status

12) 409 Conflict (create)
- Handling:
  - Not retryable; translate to ConflictError (409)
  - Provide contextual details (e.g., duplicate resource ID)

## Circuit Breaker Guidance

- Threshold: OPEN circuit after 5 consecutive failures (any retryable failure)
- Reset timeout: 30 seconds; after this, move to HALF_OPEN and allow a single test call
- HALF_OPEN behavior:
  - Success: CLOSE circuit (reset failure count)
  - Failure: return error immediately and OPEN circuit again (reset next attempt timer)

## Retry Policy

- Max retries: 3
- Base delay: 100ms
- Max delay: 1500ms
- Backoff: multiply by 2 on each attempt
- Jitter: randomize each delay by ±30–60% to reduce synchronized retries
- Retryable statuses/exceptions:
  - HTTP 408, 429, 500, 502, 503, 504
  - Connection reset (ECONNRESET), ConnectTimeout, ReadTimeout
- Non-retryable: 401, 403, 404, 409, 422
- Respect Retry-After header if present (in seconds)

## Response Examples (from downstream)

404 Not Found:
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Item not found"
  }
}

422 Validation:
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid payload",
    "details": [
      { "field": "id", "message": "Must be alphanumeric" }
    ]
  }
}

429 Rate Limit:
Headers:
- Retry-After: 2

Body:
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests"
  }
}

Note: Downstream error payloads are for logging only. Do not pass raw payloads through to clients. Translate into our standard envelope and sanitize messages.