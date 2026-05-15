# NextSteps Backlog
## Format: - [DATE] [STATUS] brief-description (context: where-mentioned)
## Statuses: OPEN, IN-PROGRESS, DONE, DISMISSED
## Max active items: 30 (archive DONE/DISMISSED items when overflow)

- [2026-04-15] OPEN Implement JWT refresh token flow (sliding window) and rotation strategy (context: auth roadmap)
- [2026-04-12] IN-PROGRESS Evaluate advanced rate limiting (leaky bucket vs sliding window) with shared store for multi-instance (context: security discussion)
- [2026-04-10] OPEN Add audit logging for auth middleware outcomes: allow/deny, reason codes (context: compliance)
- [2026-04-08] OPEN Add JTI to tokens and implement denylist on password reset/logout (context: auth improvements)
- [2026-03-30] DONE Set up CI pipeline for API with basic tests (context: devops)