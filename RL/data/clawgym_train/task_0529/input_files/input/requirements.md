# TownSquare API — High-Level Product & Security Requirements

TownSquare is a community forum API enabling users to create posts, engage with local topics, and manage accounts. Security is a first-class concern, with an emphasis on strong authentication, robust authorization, and safe-by-default session/token handling.

## Scope
- Primary clients: web and mobile.
- Authentication: token-based (primary) and session-based (for web) variants.
- Authorization: role- and permission-based (RBAC + permissions), with resource ownership enforcement.

## Objectives
- Protect user data and community content.
- Enforce least privilege and clear role boundaries.
- Provide short-lived access with secure refresh flow and revocation.
- Deter brute-force and abuse with rate limiting.
- Maintain visibility with security event logging.

## Authentication & Tokens
- Access tokens are short-lived: 15 minutes (15m).
- Refresh tokens are long-lived: 7 days (7d).
- Refresh token flow:
  - On refresh request, validate refresh token and issue a new access token.
  - Store refresh tokens server-side in a revocable store (hashed at rest).
  - Support rotation on refresh and revocation on logout.
  - Ability to revoke all refresh tokens for a user (global logout/all devices).
- Never store tokens in localStorage. Prefer httpOnly cookies or secure client storage that is not accessible to JavaScript.
- Enforce HTTPS for all environments; reject non-TLS traffic in production.

## Session (Web Variant)
- If sessions are used for web:
  - Cookies must include httpOnly, secure, and sameSite flags.
  - sameSite should default to strict unless cross-site flows are explicitly required.
  - CSRF protections must be enabled for stateful session endpoints.

## Password Policy & Storage
- Passwords must meet complexity requirements:
  - Minimum length: 12 characters
  - At least one uppercase letter, one lowercase letter, one number, and one special character
- Password hashing must use a cost factor of 12 or more rounds (no plain text storage).
- Do not log raw passwords or full tokens.

## Authorization (RBAC + Permissions)
- Roles: user, moderator, admin.
- Baseline permissions:
  - user: read:posts, write:posts
  - moderator: read:posts, write:posts, read:users
  - admin: read:posts, write:posts, read:users, write:users, delete:users
- Role hierarchy:
  - admin >= moderator >= user
- Ownership enforcement:
  - Users may modify only their own posts.
  - Admins may override ownership as needed for moderation and support actions.
  - Moderators may have separate moderation actions (e.g., content flags) without full write access to other users’ posts, unless explicitly granted.

## Endpoints (Security Expectations)
- Public:
  - POST /api/auth/register — create account (validates password policy)
  - POST /api/auth/login — rate-limited login
  - POST /api/auth/refresh — exchange valid refresh token for new access token
- Protected:
  - GET /api/users — requires read:users
  - DELETE /api/users/{id} — requires delete:users (admin-only)
  - POST /api/posts — requires write:posts
  - PUT /api/posts/{id} — requires write:posts + ownership (owner only), with admin override
- Additional protected endpoints may be added as needed following the same patterns.

## Rate Limiting
- Login endpoint: 5 attempts per 15 minutes per IP/account.
- General API: 100 requests per minute baseline (tune per route if necessary).
- Limits should return appropriate error responses and reset windows.

## Logging & Monitoring
- Log security events:
  - Login successes and failures (without sensitive data)
  - Token refresh and revocation events
  - Permission denials and suspicious activity
- Aggregate metrics for anomaly detection and incident response.
- Retain logs per compliance and privacy guidelines.

## Transport & Platform Security
- Enforce TLS with modern cipher suites and HSTS in production.
- Minimal CORS (allow only trusted origins).
- Validate all input server-side; reject malformed JSON and enforce schema for auth payloads.
- Return generic error messages to avoid information disclosure.

## Data Privacy
- Store only required PII; avoid excessive logging of sensitive data.
- Hash refresh tokens at rest; do not persist raw tokens.
- Implement data access controls consistent with roles and permissions.

## Compliance Notes
- Support user-initiated account deletion, with the required checks.
- Maintain audit trails for admin and moderation actions.