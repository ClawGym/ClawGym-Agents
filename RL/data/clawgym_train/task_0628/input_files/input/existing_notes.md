# Planning + Working Notes (messy)

Source: Assorted 1:1s, Slack threads, and whiteboard photos transcribed. Dates are when the statement was made or confirmed.

---

## Identity & Mission Fragments
- Name candidates for the assistant: "Harbor", "Scribe", "Northstar". Leaning "Harbor" because it connotes a safe, reliable place for memory.
- Mission draft: steward memory across sessions, prevent repeat mistakes, and keep decisions discoverable.

---

## Preferences & Conventions
- 2026-03-08 — Preference: Use 24-hour time in schedules and status updates.
- 2026-03-11 — Preference: No emojis in work output (Slack, docs, PRs).
- 2026-03-14 — Preference: Always create timestamped backups before any update or migration.
- 2026-02-26 — Preference: In Slack, bullets > tables for quick updates. Use tables only in docs.

"Actually" correction: Starting now, stop defaulting to Google Drive for internal docs — use the Notion "Platform" space as the single source of truth.

---

## OAuth2 Auth Flow (Contradiction present)
- 2026-01-22 — Decision (mobile app): Use OAuth2 implicit grant (expediency).
- 2026-03-05 — Decision: Switch to OAuth2 PKCE for all first-party clients; implicit grant is deprecated and increases risk. This replaces prior guidance.

Notes:
- We tested PKCE with the mobile app; the session continuity issues were resolved with proper code verifier storage.
- Action item: document the change and add a topic note.

---

## CI/CD Platform (Contradiction present)
- 2026-02-18 — Decision: Continue with Jenkins for CI due to existing pipelines.
- 2026-03-12 — Decision: Standardize on GitHub Actions; decommission Jenkins progressively. This supersedes 2026-02-18.

Rationale:
- Lower maintenance burden and tighter integration with GitHub.
- Secrets management is simpler with OIDC and repo environments.

---

## Messaging Policy
- 2026-01-15 — Decision: Slack DMs open policy for quick onboarding (temporary).
- 2026-03-10 — Decision: Switch to pairing-only DM policy to reduce noise and spoof risk.

---

## Lessons & Safety
- 2026-03-02 — Lesson: Never run database migrations directly in production. Use the staged migration pipeline with automatic backups and rollback.
- 2026-03-06 — Lesson: After any gateway restart, verify webhooks and background workers; we missed a job runner once.

---

## Entities & Projects
- ENTITY — Nimbus API: our public-facing API product under cascadelabs/nimbus-api.
- ENTITY — Project Lark: internal codename for the mobile client using Nimbus.

---

## Tooling and Environment
- Repos: github.com/cascadelabs/nimbus-api, github.com/cascadelabs/platform-infra
- Default branch: main
- Issue tracker: GitHub Issues
- Docs: Notion space "Platform"
- Calendar: Google Calendar
- Chat: Slack #platform

---

## WAL Triggers Seen in the Wild
- "Actually... when I say 'ship', I mean open a draft PR and request review."
- "From now on, use PKCE for all OAuth2 clients."
- "Do not use Jenkins going forward — create GitHub Actions workflows instead."

---

## Open Questions
- Do we need a script gate for destructive ops? Probably yes after the second violation.
- Where to put heartbeat reminders? Likely a short HEARTBEAT.md checked every 30–60 min.

End of notes.