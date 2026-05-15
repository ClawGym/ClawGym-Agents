# FreshCart — Architecture and Deployment

## High-Level Architecture
Client (React SPA) → Cloudflare CDN/WAF → AWS ALB → ECS Fargate (Node.js API) → RDS Postgres
                                                ↘ ElastiCache Redis
                                                ↘ SQS (background jobs)
                                                ↘ S3 (assets, limited user uploads)
                                                ↘ Third-party APIs (Stripe, SendGrid, Sentry, PostHog)

## Components
- Frontend
  - React SPA built and deployed to S3 + served via Cloudflare CDN (app.freshcart.com)
  - Communicates with api.freshcart.com over HTTPS (TLS 1.3 preferred)
  - CSP currently allows 'self' for scripts and styles; 'unsafe-inline' for styles still present (to be tightened)

- Edge / Network
  - Cloudflare for CDN, WAF, DNS
  - TLS 1.2+ enabled, prefer 1.3; no HSTS preload yet
  - WAF: OWASP ruleset at medium sensitivity, custom rules for login/checkout rate limits

- API Backend
  - Node.js (Express) running on AWS ECS Fargate (containers)
  - Private subnets for ECS tasks; public ALB terminates TLS and forwards to tasks
  - Input validation via joi/celebrate
  - Authentication: JWT access (15 min) and refresh (7 days) tokens; HttpOnly Secure cookies; SameSite=Lax
  - Authorization: role-based (user, admin)
  - CSRF: double-submit cookie for web form POSTs + SameSite enforcement
  - Logging: JSON logs to CloudWatch; request IDs propagated
  - Error reporting: Sentry SDK with PII scrubbing

- Database
  - Amazon RDS PostgreSQL (Multi-AZ, encrypted at rest)
  - Connection over TLS required
  - Backups: automated daily snapshots retained 7 days

- Cache
  - Amazon ElastiCache Redis (TLS enabled)
  - Uses for: short-lived session state for flows (e.g., password reset tokens, CSRF nonces), rate limiting counters, token blacklist (revocation)
  - Eviction: volatile-lru; memory alarms configured

- Asynchronous Processing
  - Amazon SQS for background jobs (email dispatch, webhook processing, receipt generation)
  - ECS worker tasks consume queues

- Object Storage
  - S3 buckets:
    - assets-freshcart: product images (public read via CloudFront)
    - uploads-freshcart: limited user uploads (profile photos) — private with signed URLs
  - Bucket policies enforce no public ACLs; Block Public Access enabled

- Third-Party Integrations
  - Stripe: Payment processing using Elements and PaymentIntents; webhooks verified (secret rotated after last incident)
  - SendGrid: Transactional email (order receipts, password reset)
  - Sentry: Error tracking (PII scrubbing, sample rate 10%)
  - PostHog: Product analytics (IP anonymized, EU consent gating)
  - Cloudflare: CDN/WAF and DNS

- Secrets and Config
  - AWS Secrets Manager for DB creds, Stripe keys, SendGrid API key
  - Parameter Store for non-secret configs
  - No secrets in container images

- CI/CD
  - GitHub Actions: build/test/lint; image scanning (Trivy) on build; deploy via Terraform + ECS task update
  - Dependency scanning with Dependabot; SAST via Semgrep on PRs

## Trust Boundaries
- Internet → Cloudflare (public to edge)
- Cloudflare → ALB (edge to AWS ingress)
- ALB → ECS services (ingress to private compute)
- App → RDS (credential boundary)
- App → Stripe/SendGrid/PostHog/Sentry (outbound to third parties)
- User → Admin (role boundary)

## Known Gaps / Work-In-Progress
- HSTS not yet enabled (planned with includeSubDomains; preload evaluation pending)
- CSP still includes 'unsafe-inline' for styles; to be reduced via nonce or hashed styles
- JWT refresh token rotation not implemented; revocation supported (Redis blacklist)
- Admin panel currently gated by credentials and role; IP allowlist not yet enforced
- No formal DDoS plan beyond Cloudflare standard protection

## Environments
- Production: AWS us-east-1
- Staging: AWS us-east-1 (separate VPC, separate third-party keys/accounts where supported)
- Dev: Local + feature branches deployed to ephemeral ECS services

---

This architecture informs component-level threat modeling and security hardening priorities.