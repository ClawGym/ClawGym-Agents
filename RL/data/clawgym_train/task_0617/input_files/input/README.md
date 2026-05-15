Endpoint Check Suite Input

Overview
- This suite is designed to verify live HTTP endpoints for status code correctness, header echo behavior, JSON body echo behavior, and basic performance measurements.

Files
- endpoints.json: Top-level JSON array of endpoint definitions. The runner should iterate these in order without adding or removing endpoints.

Fields per endpoint
- url (required): Full HTTP/HTTPS URL.
- method (required): One of GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS.
- expected_status (required): Integer HTTP status to assert.
- headers (optional): JSON object of custom headers to send.
- body (optional): JSON object to send with POST/PUT/PATCH when applicable.
- timeout (optional): Integer seconds; default to 10 if omitted.
- verify_ssl (optional): Boolean; default true if omitted.

Verification requirements
1) Status Code Matching
   - A test passes only if the final response status_code equals expected_status.
2) Header Echo Check (at least one)
   - For endpoints with custom headers, confirm the upstream echoed a provided header where supported.
   - Example: https://httpbin.org/get returns a JSON body with "headers" that should include "X-Test-Token": "abc123xyz".
3) JSON Body Echo Check (at least one POST/PUT)
   - Confirm the response body reflects the submitted JSON.
   - Example: https://httpbin.org/post and https://httpbin.org/put return objects including "json": { ...submitted JSON... }.
4) Performance
   - Capture response_time_ms for each request.
   - Identify the slowest endpoint in the report (likely https://httpbin.org/delay/1).

Output artifacts (all under output/)
- results.json: JSON array, one object per input endpoint with exactly these keys:
  - url (string, identical to input),
  - method (uppercase string),
  - expected_status (integer),
  - status_code (integer),
  - response_time_ms (integer),
  - passed (boolean),
  - body (JSON object if parseable, otherwise string),
  - notes (optional string for brief diagnostics).
- report.md: Human-readable summary including:
  - Total test count, passed, and failed lines,
  - One line per endpoint with URL, method, status_code vs expected, and response_time_ms,
  - Slowest endpoint and its duration in ms,
  - Brief root-cause analysis for any failures with next steps (e.g., header mismatch, unexpected redirect, JSON parse issue, SSL verify).

Defaults and constraints
- Timeout: Use 10 seconds unless an endpoint specifies otherwise.
- SSL: Keep verification enabled unless an endpoint specifies verify_ssl=false.
- Use only the endpoints listed in endpoints.json.
- Use relative workspace paths and write outputs only under output/.