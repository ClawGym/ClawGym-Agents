2026-04-20

User recap:
- I just refactored our Node.js Express API auth middleware (middleware/auth.js) to simplify role checks and centralize JWT verification.
- I added a basic in-memory token-bucket rate limiter (per-IP) on sensitive routes (/auth/login, /auth/refresh [planned], /api/*) — simple middleware with a 60 requests/min bucket and 10 token burst.
- We currently use HS256 JWTs signed with a single secret, no refresh tokens yet. Access token TTL is 15 minutes. No JTI or blacklist/denylist implemented.
- Goal: tighten auth and request control next, then layer in tests. Scope today is incremental improvements, not a full re-architecture.

Notes:
- Express v4, Node 18
- Rate limiter uses an in-memory map (not cluster-safe), no sliding window yet
- Middleware order: request-id → rate limiter → auth → routes
- Open questions: refresh token strategy, revocation on password reset, and how to handle token rotation during zero-downtime deploys

What I want now:
- High-quality, specific next-step suggestions grounded in this context.
- No lateral/creative ideas this time — keep it focused.
- Use the standard NextSteps format and exactly the configured number of items.
- If something relevant is already on my backlog, surface one item as a “Memory Recall”.