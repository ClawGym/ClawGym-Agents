# Q4 2026 Changelog

This changelog documents notable changes, fixes, and improvements shipped during Q4 2026.

---

## v2.1.0 — 2026-11-05
- Introduced project-scoped API tokens with granular permissions
- Added dark mode to the web console and reports
- Improved Markdown rendering for code blocks and blockquotes
- Fixed race condition in background job scheduler

### Developer Notes
- Deprecated the legacy `/v1/exports` endpoint (sunset scheduled for 2027-01-31)
- Internal: unified logging format across services

---

## v2.0.1 — 2026-10-18
- Fixed: incorrect pagination when page size exceeded 500
- Fixed: intermittent 429 errors due to stale rate-limit cache
- Improved: faster cold starts for webhook delivery service
- Docs: clarified usage of idempotency keys

---

## v2.0.0 — 2026-10-01
- Breaking: standardized HTTP status codes for validation errors
- Feature: bulk import API with progress tracking
- Feature: CSV export for aggregated analytics
- Security: rotated default signing keys and improved audit logs

### Upgrade Guide
- Update client libraries to v2.x
- Review new error schema in the API guide
- Regenerate tokens with required scopes