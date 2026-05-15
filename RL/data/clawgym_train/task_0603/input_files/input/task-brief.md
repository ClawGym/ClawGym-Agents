Task: Morning Brief and Deep-Dive from Telegram Threads + Batch Email Send

Overview:
- Summarize 6 long Telegram threads (some posts exceed typical message lengths).
- Spawn two sub-agents:
  1) Morning Brief: concise, executive-friendly summary.
  2) Deep-Dive: detailed analysis with references and action items.
- Deliverables:
  - Telegram-ready snippets for posting (safe length).
  - Email report to ~150 recipients using gog gmail send (single batch).

Constraints and Risks:
- Telegram message length limits (avoid API errors; ensure messages are under safe limits and properly chunked if needed).
- Sub-agent output quality often degrades without explicit success criteria and reference materials.
- Email batch could hit provider rate limits or fail if OAuth is stale.

Acceptance Criteria:
- Morning Brief messages post without errors (no chunk over limit).
- Deep-Dive is linked in the email body; any long content is hosted or attached only if within size limits.
- Sub-agent specs include: inputs, references, success criteria, and evaluation check.
- Email batch succeeds without 429 rate limits; include throttle/backoff if required.
- No security policy violations (e.g., do not disable TLS verification).