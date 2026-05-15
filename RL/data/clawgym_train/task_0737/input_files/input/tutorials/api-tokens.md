# API Tokens and Scopes

This tutorial explains how to create, scope, rotate, and revoke API tokens safely. It includes a hands-on walkthrough and a catalog of API token scopes.

---

## Why scopes matter

Scopes enforce least privilege by limiting what a token can do. For example:
- A token with `read:projects` cannot create or delete projects.
- A token with `manage:tokens` can create and revoke other tokens—guard this carefully.

---

## Creating a token (dashboard)

1) Open the “Tokens” page.
2) Click “New token”.
3) Choose a name and expiration (optional).
4) Select “API token scopes”:
   - read:projects
   - write:projects
   - read:org
   - manage:tokens
   - search:query
   - search:index.update
   - billing:read
   - billing:write (Enterprise)
5) Restrict by IP ranges if needed (CIDR).
6) Create and copy the token value once; store securely.

---

## Creating a token (API)

```
POST /v1/tokens
Authorization: Bearer {admin_or_manage:tokens_token}
Content-Type: application/json

{
  "name": "ci-deploy",
  "scopes": ["write:projects", "search:index.update"],
  "ip_allowlist": ["203.0.113.0/24"]
}
```

Response:
```
{
  "id": "tok_123",
  "token": "acme_pat_******",
  "scopes": ["write:projects", "search:index.update"],
  "created_at": "2026-02-15T12:00:00Z"
}
```

---

## API token scopes (catalog)

Core:
- read:projects — List and read project metadata
- write:projects — Create and update projects
- read:org — Read organization information
- manage:tokens — Create, rotate, and revoke tokens

Search:
- search:query — Execute keyword and semantic search
- search:index.update — Perform an index update (incremental or full)

Billing:
- billing:read — Read invoices, usage, and balance
- billing:write — Update payment methods and billing settings (Enterprise only)

Admin:
- admin:all — Superset for break-glass operations; avoid in normal practice

Tips:
- Combine only the scopes you need per integration.
- Separate deployment and read-only tokens to limit blast radius.

---

## Rotating tokens

- Create a new token with the same scopes.
- Deploy the new token to clients.
- Revoke the old token after verifying traffic cutover.
- Automate rotation every 90 days.

---

## Revoking tokens

```
POST /v1/tokens/{id}:revoke
Authorization: Bearer {manage:tokens_token}
```

- Revocation is immediate for new requests.
- Audit logs record who revoked which token and when.

---

## Auditing and alerts

- Use the audit log to monitor token creation and revocation.
- Enable alerts for high-privilege scope usage (e.g., admin:all).

---

## Examples

Read-only CI token:
- scopes: [“read:projects”, “search:query”]
- ip_allowlist: your build network
- rotation: 60 days

Indexing worker:
- scopes: [“search:index.update”]
- runs on a private network
- rotates service secrets separately from PATs

---

## Troubleshooting

- 403 Forbidden: The token is missing required scopes for the endpoint; verify “API token scopes.”
- Accidental over-scoping: Revoke and reissue with least privilege.
- IP allowlist mismatch: Update CIDRs or remove to test.

---

# End of API tokens tutorial