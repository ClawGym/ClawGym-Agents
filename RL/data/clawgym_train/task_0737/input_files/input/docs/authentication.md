# Authentication

This document explains how clients authenticate with the Acme Dev Platform APIs. It covers the full authentication flow for web and native apps, service-to-service credentials, and common pitfalls.

We support:
- OAuth 2.1 with PKCE (recommended for web and native apps)
- OAuth 2.1 Client Credentials (machine-to-machine)
- Personal API tokens (scoped, for CLI and quick starts)
- Device code flow (low-UI devices and headless CLIs)

Security defaults:
- Access tokens are short-lived (1 hour)
- Refresh tokens are long-lived (30 days) and rotate on use
- TLS is required for all endpoints
- Scopes and audiences must be requested explicitly when relevant

---

## Authentication flow (PKCE, Web or Native Apps)

Use this authentication flow for user-facing applications. It keeps secrets out of the browser while protecting against interception and replay.

1) Generate a code verifier and challenge (client-side):
- code_verifier: 43–128 random characters
- code_challenge = BASE64URL(SHA256(code_verifier))

2) Redirect the user to authorize:
- GET /oauth/authorize
- Parameters:
  - response_type=code
  - client_id={your_client_id}
  - redirect_uri={your_redirect_uri}
  - scope={space-separated scopes}
  - code_challenge={pkce_challenge}
  - code_challenge_method=S256
  - state={csrf_token}

3) User signs in and approves requested scopes.

4) Exchange the authorization code for tokens:
- POST /oauth/token
- Body:
  - grant_type=authorization_code
  - client_id={your_client_id}
  - code={authorization_code}
  - redirect_uri={your_redirect_uri}
  - code_verifier={original_verifier}

5) Receive tokens:
- access_token (JWT or opaque)
- token_type = Bearer
- expires_in = 3600
- refresh_token (when offline_access requested)
- scope (granted scopes)

6) Use the access token:
- Authorization: Bearer {access_token}
- Retry with refresh when you receive a 401 due to token expiration.

7) Refresh tokens when needed:
- POST /oauth/token
- grant_type=refresh_token
- refresh_token={refresh_token}
- client_id={your_client_id}

Notes:
- The above is the primary authentication flow for interactive apps.
- If you request audience-specific tokens, include `audience` during authorize.
- Use PKCE for all public clients; do not embed a client secret in browser code.

Example token exchange (step 4):

```
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&
client_id=app_123&
code=SplxlOBeZQQYbYS6WxSbIA&
redirect_uri=https%3A%2F%2Fapp.example.com%2Fcallback&
code_verifier=2cfd...f3a
```

---

## Authentication flow (Client Credentials, Service-to-Service)

For back-end integrations where no user is present, use the client credentials flow.

1) Obtain a machine client_id and client_secret from the dashboard (or via admin API).
2) Request a token:
```
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&
client_id=svc_abc&
client_secret=********&
scope=read:projects write:projects
```
3) Use the returned access token in Authorization headers.

Scope tips:
- Grant the minimal required scopes (principle of least privilege).
- Rotate secrets regularly; use the dashboard or API to rotate without downtime.

---

## Authentication flow (Device Code Flow)

For devices without a full browser or keyboard:

1) App starts the device code flow:
```
POST /oauth/device/code
client_id=app_123&scope=read:projects offline_access
```
2) The API returns:
- user_code (e.g., H7TF-9JKL)
- verification_uri (e.g., https://acme.dev/activate)
- device_code and interval (polling hints)
3) Instruct the user:
- “Go to https://acme.dev/activate and enter H7TF-9JKL.”
4) Poll for token:
```
POST /oauth/token
grant_type=urn:ietf:params:oauth:grant-type:device_code
device_code=...
client_id=app_123
```
5) On success, you receive access_token and optional refresh_token.

---

## Personal API Tokens (PATs)

For quick starts and CLIs, you can use a Personal API Token:
- Created in the dashboard by the user
- Bound to the user, revocable at any time
- Limited by scopes and (optionally) IP ranges
- Sent as `Authorization: Bearer {token}`

Use cases:
- Local scripts
- CI jobs (with careful scoping)
- Short-lived demos and testing

---

## Example: Making an authenticated request

```
GET /v1/projects
Authorization: Bearer eyJhbGciOi...
Accept: application/json
```

Expected 200 response with JSON list of projects. If the token is expired or missing scopes, you may receive:
- 401 Unauthorized (invalid/expired token)
- 403 Forbidden (valid token, insufficient scopes)

---

## Scopes

Common scopes:
- read:projects — List and read project metadata
- write:projects — Create or update projects
- read:org — Read organization information
- manage:tokens — Create, rotate, and revoke tokens
- search:query — Execute search requests
- search:index.update — Perform an index update operation
- billing:read — Read invoices, usage, and balance
- billing:write — Manage billing sources (Enterprise)

Request only what you need to minimize risk.

---

## Token lifetimes and rotation

- Access tokens: 1 hour
- Refresh tokens: 30 days (rotate on each refresh)
- Client secrets: rotate at least every 90 days

Rotating refresh tokens:
- Refresh responses return a new refresh_token
- Store the new one and discard the old one
- If you lose track, revoke all refresh tokens in the dashboard and re-authenticate

---

## Common errors and fixes

- invalid_grant — The authorization code is invalid or expired. Restart the authentication flow.
- invalid_scope — You requested scopes not allowed for your app. Adjust dashboard settings.
- invalid_client — Client secret or client_id is wrong. Check your configuration.
- invalid_audience — The audience parameter is incorrect or not allowed. Verify audience values.

---

## Gotchas

- Clock skew: If server and client clocks differ by >5 minutes, token validation can fail.
- Missing offline_access: You won’t receive a refresh token without this scope in the initial authentication flow.
- Over-scoping: Requesting admin:all may require explicit admin approval; prefer narrow scopes.
- Token location: Always send tokens in the Authorization header, not in query parameters.
- Audience mismatch: A token minted for audience “analytics” won’t work for “realtime”; request the correct audience during authorization.

---

## Revocation

- Revoke tokens and refresh tokens via the dashboard or API:
```
POST /oauth/revoke
token={access_or_refresh_token}
token_type_hint=access_token
```
- Revocation is immediate for future calls; in-flight requests may still succeed.

---

## Testing

- Sandbox base URL: https://api.sandbox.acme.dev
- Real data base URL: https://api.acme.dev
- Use separate applications and tokens per environment to avoid accidental cross-use.

---

## Related tutorials

- “Getting Started” for a quick walkthrough of token creation
- “API tokens and scopes” for hands-on steps to manage scopes safely

---

# End of authentication documentation