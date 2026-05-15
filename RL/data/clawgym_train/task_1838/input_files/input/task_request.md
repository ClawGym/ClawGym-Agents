Project: Commerce API

Request date: 2026-04-15
Requester: Product (Growth)

Change summary:
- Implement a new public Orders listing API endpoint to support marketing pages and potential partner integrations.
- Run a quick security audit on the OpenClaw gateway and host to ensure we are not exposing obvious risks.

Functional details for Orders listing API:
- Endpoint: GET /orders (under existing API host)
- Purpose: Allow listing recent orders for embedding in marketing pages and for early partner evaluation.
- Required response fields per order: id, number, status, total_amount, currency, created_at
- Sorting: created_at desc by default
- Pagination: page + per_page (default per_page=20, max per_page=100)
- Data constraints: Do not include PII (no customer name, email, address).
- Filtering: Not required for v1; simple list only.

Open questions (intentionally not finalized yet):
- Authorization: Not specified. We’ve said “public” informally but have not agreed on final auth rules (bearer token vs. unauthenticated vs. IP allowlist).
- Consumers: Unknown list. Could be our own frontend embeds, a few marketing pages, and maybe pilot partners; no definitive consumer registry yet.
- Rate limits: Not yet defined.
- Observability: Basic API logs exist; no custom metrics planned yet.

Non-functional notes:
- Runtime: See input/app_context.json for PHP/framework/DB versions and system shape.
- Please produce a clear API contract for GET /orders and flag any stop-work items if needed.
- Run a 10-point quick security audit using the provided input/openclaw.json and input/host_facts.json and output a JSON report.

Acceptance hints (for later refinement):
- API returns only the approved fields and paginates correctly.
- Default sort is created_at desc.
- per_page clamps to 100 if higher is requested.
- No PII is leaked.
- Security audit output is structured and highlights any critical risks.

Timeline:
- Draft contract + risk/stop-work assessment today.
- Implementation pending security and contract approval.