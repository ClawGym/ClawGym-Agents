# Product Requirements: Error Handling & API Behavior

These requirements define the expected error handling behavior for the Python HTTP API service.

## Error Response Standard

All failures must return a standard JSON error envelope:
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message without internal details",
    "details": [optional array/object with safe context],
    "requestId": "correlation-id-for-this-request"
  }
}

Rules:
- Include requestId on every error response (see Correlation ID below)
- Do not expose stack traces, file paths, SQL, or internal error messages in the API response
- Keep details minimal and safe; use server-side logs for full diagnostic information

## HTTP Status Codes

Use appropriate status codes:
- 400 Bad Request — malformed request, invalid JSON, missing required fields
- 401 Unauthorized — authentication missing or invalid
- 403 Forbidden — authenticated but lacking permissions
- 404 Not Found — resource does not exist
- 409 Conflict — duplicate or conflicting state (e.g., creating an existing resource)
- 422 Unprocessable Entity — semantically invalid input (validation failures)
- 429 Too Many Requests — rate limit exceeded; include Retry-After header if applicable
- 500 Internal Server Error — unexpected server errors (programmer errors or unhandled cases)
- 502 Bad Gateway — upstream/downstream returned invalid/malformed response
- 503 Service Unavailable — downstream unavailable or maintenance (operational)

## Correlation ID

- Accept X-Request-ID header from clients; if absent, generate a random ID (e.g., req_<uuid or timestamp_random>)
- Include requestId in:
  - Every error response envelope
  - Structured logs for requests and errors
- Propagate requestId to downstream calls via headers (X-Request-ID)

## Structured Logging

Log in structured JSON (one line per event) including:
- timestamp (ISO 8601)
- level (info, warn, error)
- message (short description)
- requestId
- method
- path
- statusCode
- latencyMs
- error.code and error.message for failures
- Optionally: userId if known (do not log secrets or PII)

Logs are for server-side diagnostics; never include internal details in client responses.

## Operational vs Programmer Errors

- Operational errors: network timeouts, downstream 503/502, rate limits (429), invalid user input (422). Handle gracefully with custom exceptions and standard envelope.
- Programmer errors: TypeError, NameError, assertion failures, null dereference. Do not catch silently. Let the centralized error handler return a generic 500 with a safe message and log the full error.

## Centralized Error Handling

- Implement a single error handler at the framework boundary to translate AppError subclasses into JSON envelopes
- Catch specific operational errors and convert them into domain-specific AppError instances
- Allow unexpected exceptions to bubble up; centralized handler should return 500 with a safe message
- Never use bare "except:"; do not swallow errors silently

## Downstream Reliability

Wrap downstream calls with retry and a circuit breaker:
- Retry: exponential backoff with jitter
  - max_retries: 3
  - base_delay: 0.1s
  - max_delay: 1.5s
  - Jitter: randomized ±30-60% on each attempt
  - Retry conditions: 408, 429, 500, 502, 503, 504, connection reset (ECONNRESET)
  - Do not retry: 401, 403, 404, 409, 422
  - Respect Retry-After header if present (wait at least that duration before retry)
- Circuit breaker:
  - threshold: open the circuit after 5 consecutive failures
  - reset timeout: 30 seconds, then transition to HALF_OPEN
  - HALF_OPEN: allow a single trial call; on success, close the circuit; on failure, reopen

## Response Behavior Summary

- Correct status codes and a consistent JSON error envelope
- requestId present in responses and logs
- No stack traces or raw upstream payloads in client responses
- Graceful handling of operational errors; programmer errors become 500 with safe messaging
- Downstream calls protected with retry + jitter and a circuit breaker

## Anti-Patterns to Avoid

- Swallowing exceptions silently
- Bare "except:" catching everything
- Returning raw downstream error bodies directly
- Logging and throwing at every layer; log at boundaries (controller/middleware)
- Using exceptions for normal control flow
- Caching error responses