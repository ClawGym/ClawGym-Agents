# Agent Contact Card — Overview

Agent Contact Card is a simple, text-based way to publish how AI agents can be contacted and how they prefer to be routed. Think of it like a vCard for agents. A single markdown file with YAML frontmatter is hosted at a well-known path so other agents can find it, parse the structured fields, and follow the natural-language routing rules in the body.

Core ideas:
- File format: Markdown with YAML frontmatter. Machines parse the frontmatter; humans and agents read the body for routing rules.
- Location: Prefer the well-known path `/.well-known/agent-card` on a domain. Variants may exist for named or private tiers.
- Purpose: Allow agents to choose the right channel (email, Discord, webhook, etc.) for the right job, with clear expectations on response time, escalation, and authentication.
- Scope: Supports single-agent and multi-agent setups. Encourages privacy-aware publication of contact paths with optional privacy tiers.

What the frontmatter contains:
- Required fields: `version: "1"`
- Recommended fields: `human_contact`, `channels`
- Optional fields: `name`, `last_updated`, `capabilities`, `agents` (for multi-agent routing), `public_key`

What the body should describe:
- Routing guidance: which channel to use for scheduling, support, urgent requests, etc.
- Authentication or verification rules for sensitive actions
- Escalation rules to a human
- Any channel-specific format instructions (e.g., webhook JSON schema)

Channels and webhooks:
- Channels are named endpoints (email address, Discord handle, phone number, webhook URL).
- Webhooks should specify method, expected payload format, and any auth requirements (e.g., Bearer tokens, signatures).

Multi-agent support:
- List specialized agents in `agents[]` with `name`, `handles` (topics), a primary `channel`, and an `id` (address/URL/handle).
- The body explains how to route among them.

Privacy tiers:
- Public card at `/.well-known/agent-card` for general use.
- Named cards at `/.well-known/agent-card/{name}` for professional contexts.
- Private cards at a random path for restricted sharing.

Discovery methods:
- Check the well-known URL on the domain.
- Look for a vCard field that points to the agent card (e.g., `X-AGENT-CARD`).
- If not found, ask the human for the URL.

Security and privacy:
- Never publish secrets. Use tokenized or capability-limited channels.
- Document verification and escalation for sensitive operations.

Versioning and compatibility:
- Current spec uses `version: "1"`. Future versions should remain backwards compatible where possible.