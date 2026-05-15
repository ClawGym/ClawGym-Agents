Users API — Production-Grade Async FastAPI Skeleton

Overview
- Build a small, production-grade async FastAPI service focused on a “Users” domain.
- Implement a minimal feature set to register users, authenticate (login), and list users with admin-only access.
- Include health and readiness endpoints; readiness should exercise the repository layer.
- Use strict Router → Service → Repository layering with dependency injection; routers are thin and services hold business logic.
- Use Pydantic v2 for input/output schema validation; validate at API boundaries and never expose passwords in responses.

Scope
- Endpoints to implement (details in endpoints.json):
  - POST /api/users — register a new user (public/open).
  - GET /api/users — list users (admin-only).
  - POST /api/auth/login — issue access token (public/open).
  - GET /health — liveness probe.
  - GET /ready — readiness probe exercising repository.
- Users entity details and constraints in entities.yaml.

Non-Functional Requirements
- Async by default for all I/O paths; repositories should be async (database can be stubbed).
- Environment-backed configuration via Pydantic Settings:
  - Fail fast on required secrets; do not provide defaults for jwt_secret and database_url.
  - Provide a cached getter (e.g., lru_cache) to avoid repeated parsing.
  - Expose debug flag to control docs visibility at runtime.
- Structured error handling:
  - Define AppError base class and domain-specific subclasses (NotFoundError, AuthenticationError).
  - Register a global exception handler that returns structured JSON: {"error": {"code", "message", "details"}}.
  - Never return bare strings or stack traces.
- Authentication and Authorization:
  - Token-based (JWT). Tokens should include sub and roles.
  - Provide dependency to load current user from token; return AuthenticationError if invalid/expired.
  - Role-based guard helper; GET /api/users must be admin-only.
- Schemas and Validation:
  - Separate input (UserCreate) from output (UserResponse); never include password in responses.
  - Validate email format, password length (min 8), and name length limits.
- Observability:
  - Structured JSON logging. Include a request ID bound to logs and returned in response header (e.g., X-Request-ID).
  - Liveness endpoint: returns {"status": "ok"} with 200.
  - Readiness endpoint: attempts repository operation (e.g., ping or count); returns 200 if healthy else 503, with a body indicating component statuses.
- Project Structure:
  - Feature-based modules; strict layering.
  - App factory pattern (create_app) wiring routers/middleware/handlers.
  - Docs exposed only when Settings.debug is true.

Testing
- Provide at least one async end-to-end style test:
  - Exercise POST /api/users (register) and ensure the response never includes password and returns 201.
  - Exercise GET /health (200).
  - Optional bonus: login then call GET /api/users with/without admin role.

Notes and Implementation Hints
- Repository layer can be an in-memory async stub for this scaffold.
- Ensure duplicate email handling is at least considered (409) with structured error; if not implemented, document that it’s a TODO.
- Token claims should include roles list to support the role guard.
- Readiness should call repository.ping() or a minimal query to validate health; in-memory stub can always be “ok”.
- Return paginated structure for list endpoints if feasible (page, page_size, total, has_next), but a simple list is acceptable for the scaffold as long as schemas validate and roles are enforced.