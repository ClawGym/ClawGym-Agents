# Acme API Guide

Welcome to the Acme API. This guide provides an overview of endpoints, authentication, and common patterns to help you integrate quickly and reliably.

## Authentication
Requests must include a bearer token with the appropriate scopes in the `Authorization` header:
`Authorization: Bearer <token>`

Tokens are project-scoped and can be rotated without downtime. For long-running jobs, we recommend short-lived tokens combined with refresh flows.

## Endpoints Overview
Below is a quick reference table for frequently used endpoints.

<table>
  <thead>
    <tr>
      <th>Endpoint</th>
      <th>Method</th>
      <th>Description</th>
      <th>Requires Auth</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>/v2/projects</td>
      <td>GET</td>
      <td>List projects visible to the token</td>
      <td>Yes</td>
    </tr>
    <tr>
      <td>/v2/projects/{id}</td>
      <td>GET</td>
      <td>Retrieve a project by its identifier</td>
      <td>Yes</td>
    </tr>
    <tr>
      <td>/v2/exports</td>
      <td>POST</td>
      <td>Create a new export job (CSV or JSON)</td>
      <td>Yes</td>
    </tr>
  </tbody>
</table>

## Idempotency
For safe retries, include an `Idempotency-Key` header with a UUID per unique operation. The server guarantees that repeated requests with the same key will not perform the action more than once.

## Errors
All error responses include a machine-readable code and human-friendly message:
- code: a stable string identifier (e.g., `validation_failed`)
- message: a concise explanation (e.g., “email is required”)
- details: optional field with per-field validation issues

## Rate Limiting
The API enforces fair-use limits and returns standard rate-limit headers:
- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`

Back off using exponential delays when receiving HTTP 429 status codes.