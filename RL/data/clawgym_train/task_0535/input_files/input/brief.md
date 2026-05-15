Self-Improvement Audit Brief

Scope
- Read the transcript at input/conversation.jsonl and identify all triggering events.
- Write structured entries for each trigger to:
  - output/.learnings/LEARNINGS.md — user corrections (category: correction)
  - output/.learnings/ERRORS.md — external tool/API failures
  - output/.learnings/FEATURE_REQUESTS.md — missing capability requests

Triggers to capture
- Explicit user corrections about the assistant’s mistake (phrases like “No, that’s wrong” or “You made an error”).
- External tool/API failures (HTTP/tool timeouts, file errors, etc.).
- Missing capability requests (e.g., user asks for a feature the agent doesn’t have yet).

Anti-loop guardrails
- One learning per user message. Do not log multiple learnings from a single user message.
- No chaining. Do not trigger additional self-improvement actions from the logging itself.
- Cooldown until the next user message before considering a new learning.
- Do not perform promotions or reviews in this pass—logging only.

ID format and sequencing
- Each entry header must be: ## [TYPE-YYYYMMDD-XXX] …
  - TYPE: LRN, ERR, or FEAT
  - YYYYMMDD: 8-digit current date
  - XXX: Three-digit sequence starting at 001 and increasing by 1 within each file
- Sequences are independent per file (each file starts at 001).

Priorities and status
- Corrections (LEARNINGS.md): Priority high; Status pending
- Errors (ERRORS.md): Priority high; Status pending
- Feature requests (FEATURE_REQUESTS.md): Priority medium; Status pending

Required content per entry

1) Learning Entry (user correction)
- File: output/.learnings/LEARNINGS.md
- Category in header: correction
- Template:
## [LRN-YYYYMMDD-XXX] correction

**Logged**: 2025-01-15T10:30:00Z
**Priority**: high
**Status**: pending

### Summary
One-line description of the correction

### Details
What was wrong vs. the correct behavior, using concrete terms from the transcript

### Suggested Action
Specific next step to avoid repetition
---

2) Error Entry (tool/API failure)
- File: output/.learnings/ERRORS.md
- Template:
## [ERR-YYYYMMDD-XXX] command_or_tool

**Logged**: 2025-01-15T10:30:00Z
**Priority**: high
**Status**: pending

### Summary
Concise description of what failed

### Error
Exact error text from the tool or API

### Context
Command or tool that was attempted, plus any relevant parameters/URLs/paths

### Suggested Fix
Actionable fix or mitigation (e.g., retries, backoff, path checks)
---

3) Feature Request Entry (missing capability request)
- File: output/.learnings/FEATURE_REQUESTS.md
- Template:
## [FEAT-YYYYMMDD-XXX] capability_name

**Logged**: 2025-01-15T10:30:00Z
**Priority**: medium
**Status**: pending

### Requested Capability
Short description of the requested feature

### User Context
Why the user needs it and how they plan to use it

### Complexity Estimate
simple | medium | complex
---

Checklist for this audit
- Identify each explicit user correction and log exactly one learning entry per such message.
  - Ensure one entry mentions both “tax” and “shipping” in Summary or Details.
  - Ensure another entry mentions “discount” and “before tax” in Summary or Details.
- Identify each tool/API failure and log exactly one error entry per failure.
  - One Error section must include the word “timeout”.
  - Another Error section must include “No such file or directory”.
- Identify the feature request for CSV export and log exactly one feature entry.
  - Include both words “export” and “csv” in the capability or context.
- Use ISO-8601 timestamps in **Logged** fields.
- Keep summaries concise; details must clearly state what was wrong and what is correct.
- Suggested Action / Suggested Fix must be specific and actionable.
- Do not write anywhere outside output/.