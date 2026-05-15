Acceptance Tests — Users API

AT-1: Register User (Public)
- Given I POST to /api/users with a JSON body:
  {
    "email": "user1@example.com",
    "name": "User One",
    "password": "TopSecret123"
  }
- Then I receive a 201 Created.
- And the response body includes: id (UUID), email, name, roles (default ["user"]), created_at (ISO8601).
- And the response body DOES NOT include "password" anywhere.
- And email format and password (>=8 chars) are validated at the API boundary.

AT-2: Login (Token Issuance)
- Given I have a user registered with email "user1@example.com" and password "TopSecret123".
- When I POST to /api/auth/login with:
  { "email": "user1@example.com", "password": "TopSecret123" }
- Then I receive 200 OK and a JSON body:
  { "access_token": "<jwt>", "token_type": "bearer" }.
- And the JWT contains "sub" (user id) and "roles" (array), and an expiration.

AT-3: List Users (Admin-Only)
- Given there is at least one user in the system.
- And I have a valid access token for a non-admin user.
- When I GET /api/users with the non-admin token
- Then I receive 403 Forbidden with a structured error:
  {
    "error": {
      "code": "FORBIDDEN",
      "message": "Insufficient permissions",
      "details": {}
    }
  }

- Given I have a valid access token for an admin user (roles includes "admin").
- When I GET /api/users with the admin token
- Then I receive 200 OK and a paginated response containing an "items" array of users.
- And each user item contains id, email, name, roles, created_at and NEVER a password field.

AT-4: Health and Readiness
- When I GET /health
- Then I receive 200 OK and a JSON body: { "status": "ok" }.

- When I GET /ready
- Then the service performs a repository health check (e.g., ping, count).
- If repository is healthy, I receive 200 OK with:
  { "status": "ok", "checks": { "repository": "ok" } }.
- If repository is unhealthy (simulate failure in repo layer), I receive 503 with:
  { "status": "degraded", "checks": { "repository": "error" } }.

AT-5: Structured Errors
- For any domain error (e.g., invalid credentials, resource not found), responses must follow:
  {
    "error": {
      "code": "<UPPER_SNAKE_NAME>",
      "message": "<human-readable>",
      "details": { ... }
    }
  }
- No bare strings; no stack traces in responses.

AT-6: Configuration Fail-Fast
- If required environment variables (jwt_secret, database_url) are missing at startup,
  then the application fails fast (does not start).
- Settings are cached (lru_cache) and secrets are not defaulted.

AT-7: Logging and Request ID
- Each request is assigned a request_id (from X-Request-ID header or generated).
- request_id is bound into structured JSON logs and returned in the response header (X-Request-ID).