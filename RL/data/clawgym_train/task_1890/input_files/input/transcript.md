# Chat Excerpt — 2026-04-16

User: Quick correction on your setup instructions — we do NOT use npm here.
We use pnpm across the monorepo. The lock file is pnpm-lock.yaml, not package-lock.json.
Please make sure future instructions say "pnpm install" instead of "npm install."

Assistant: Got it. I'll switch to pnpm in all commands.

User: Also, our backend must include the X-Correlation-ID header in every API response.
It should echo the value from the incoming request header.
If the request doesn't include it, generate one and return it so tracing is consistent.

Assistant: Understood. We'll ensure a middleware is in place to read the request header and write it back on responses.

User: One more thing that keeps biting us after OpenAPI spec changes:
after we update openapi.yaml, we need to regenerate the TypeScript API client and verify types compile cleanly.
The exact commands we run are:
- pnpm run generate:api
- pnpm tsc --noEmit

Assistant: Thanks — I’ll capture that as a learning and add it to the workflow.

User: Feature request: can you add a simple “daily digest” function that summarizes .learnings/
pending items at session start? I want the digest to show:
- count of pending learnings by priority,
- list of pending high-priority items with IDs and one-line summaries,
- and a short reminder of any learnings that were promoted in the last 24 hours.
Ideally this could run as a hook or a small script we can trigger manually.

Assistant: Sounds good. I’ll file this as a feature request and propose a hook plus a script approach.

User: Great. Please also reference the prior learning LRN-20250110-001 about our package manager in your new entries so we can track the recurrence.