# Incident BR-2026-03-01 — Auth Session Regression

Detected: 2026-02-29 21:12 UTC
Resolved: 2026-03-01 14:32 UTC
Affected users: 127 (sessions interrupted during OAuth callback window)

## Summary
Users experienced unexpected sign-outs immediately after returning from OAuth. Session cookies were not persisted across the OAuth redirect, causing the app to treat authenticated users as anonymous.

## Root Cause
Chrome and other modern browsers enforce SameSite=Lax by default. Our app’s session cookie lacked explicit attributes and therefore defaulted to SameSite=Lax, which blocks the cookie on cross-site POST redirects from the OAuth provider. Result: session cookie not sent on the callback, leading to apparent logout.

- Problematic default: SameSite=Lax (implicit)
- Missing attributes: SameSite=None; Secure

## Resolution
- Update session cookie configuration to set SameSite=None; Secure.
- Regenerated cookie secrets and rotated sessions.
- Deployed hotfix to production on March 1, 2026 (14:32 UTC).

## Impact and Verification
- Impact window: ~17 hours.
- 127 unique users required re-authentication.
- Post-deploy verification: OAuth callback retained session; regression tests added.

## Follow-ups
- Add an automated config check in CI for cookie attributes.
- Document cookie policy in security checklist.