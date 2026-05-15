# Getting Started

Welcome to the Acme Dev Platform! This tutorial walks you through creating your first API request in minutes. You will create an organization, generate a token, complete the authentication flow, and call a simple endpoint.

---

## 1) Create an account and organization

- Sign up in the dashboard.
- Create an organization (you can invite teammates later).
- Note your organization ID for API usage.

---

## 2) Generate a Personal API Token

- Navigate to “Tokens” in the dashboard.
- Click “New token” and select scopes, e.g., `read:projects`.
- Copy the token; you won’t be able to view it again.
- Store it securely (e.g., in a secrets manager).

---

## 3) Complete the authentication flow

For user apps, use the PKCE authentication flow described in the authentication docs:
- Generate a code verifier and challenge.
- Redirect to authorize with `code_challenge=S256`.
- Exchange the code for tokens.
- Use the access token in Authorization headers.

For quick starts, your Personal API Token is sufficient.

---

## 4) Make your first API call

```
curl -H "Authorization: Bearer $ACME_TOKEN" \
     https://api.acme.dev/v1/projects
```

Expected response:
- 200 OK
- A JSON list of projects (empty if none created yet)

---

## 5) Understand rate limiting

- Default: 120 requests per minute per token.
- On 429, read `Retry-After` header and retry with backoff.
- Batch or cache where possible.

---

## 6) Next steps

- Explore “API token scopes” to tailor permissions.
- Learn about “semantic search” and “hybrid search.”
- Set up webhooks to trigger an index update when docs change.

---

## Troubleshooting

- 401 Unauthorized: Check token validity and that you used the right environment (sandbox vs prod).
- 403 Forbidden: Likely missing scopes; adjust the token’s “API token scopes.”
- 429 Too Many Requests: Respect `Retry-After` and implement backoff.

---

# End of getting started