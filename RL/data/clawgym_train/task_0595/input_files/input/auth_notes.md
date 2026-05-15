# Authentication Notes — Acme TaskFlow

Overview
- Auth is powered by NextAuth.js using JWT sessions and httpOnly, secure cookies.
- App Router (app/) only. No Pages Router features are used.

Prerequisites:
- NEXTAUTH_SECRET set in server environment
- At least one provider configured (Email or OIDC); credentials flow only for internal admin
- Secure cookies enabled; HTTPS enforced in production

Server Usage
- In Server Components and Server Actions, call auth() or getServerSession() to retrieve the session.
- API Routes (app/api/*/route.ts) must verify a valid session before accessing protected resources.
- Never send raw tokens to the client; derive minimal claims when needed.
- Authorization: enforce role (user/admin) and team-scoped access checks on the server.

Client Usage
- Client Components must use useSession() (or a small session wrapper) for UI gating only.
- Never import Prisma or read process.env from the client; do not perform direct DB queries.
- For mutations and reads, call Server Actions or fetch API routes (authenticated via cookies).
- Handle sign-in/out via NextAuth Client helpers; errors surfaced via toasts/snackbar.

Session & Security Rules
- Session TTL: 7 days rolling; refresh on activity; revoke on logout.
- Rotate NEXTAUTH_SECRET quarterly; invalidate old tokens on rotation.
- CSRF: rely on NextAuth built-ins for auth routes; perform origin checks on custom POST routes.
- Logging: never log JWTs, session IDs, or PII at INFO level.

Common Paths (for reference)
- app/api/auth/[...nextauth]/route.ts — NextAuth route handler
- app/(server)/actions/tasks.ts — Server Actions wrapping protected DB access
- lib/auth/session.ts — Small helpers: isAdmin(session), getTeamIds(session)

Negative Constraints
- Do NOT use getServerSideProps (Pages Router only; we use App Router).
- Do NOT paste full code blocks from third-party docs; summarize and adapt to our stack.