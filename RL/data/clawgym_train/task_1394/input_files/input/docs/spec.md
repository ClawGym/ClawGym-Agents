# Agent Contact Card — Specification

Version: 1 (draft-stable)

1) File Format
- A UTF-8 markdown file with YAML frontmatter.
- The frontmatter provides structured fields; the markdown body provides natural-language routing rules.
- Recommended MIME type when served over HTTP: `text/markdown` (or `text/plain`).

Structure:
```markdown
---
version: "1"
# other structured fields here
---

# Title (optional)
Routing and instructions in natural language...
```

2) Frontmatter Fields

Required
- version (string): Spec version. Currently "1".

Recommended
- human_contact (string): How a human can reach the human owner (e.g., phone or email).
- channels (object): Contact endpoints for agents, keyed by channel name.

Optional
- name (string): Display name for this card.
- last_updated (string, ISO date): Last modification date (e.g., "2026-04-18").
- capabilities (array): Capabilities offered (e.g., ["scheduling", "accepts_ical", "support_tickets"]).
- agents (array): Specialized agents for multi-agent configurations.
- public_key (string, PEM): Public key for verifying or encrypting webhook traffic or signed messages.

Example fields:
```yaml
version: "1"
name: "Example Agents"
human_contact: "support@example.org"
last_updated: "2026-04-18"
capabilities:
  - scheduling
  - accepts_ical
channels:
  email: "agents@example.org"
  discord: "example-agent#1234"
  webhook:
    url: "https://example.org/agent/incoming"
    method: "POST"
    auth: "Bearer <token> in Authorization header"
    format: "JSON with 'message' and 'from' fields"
public_key: |
  -----BEGIN PUBLIC KEY-----
  MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...
  -----END PUBLIC KEY-----
```

3) Channels

- Channel names are flexible (email, discord, signal, telegram, slack, webhook, imessage, etc.).
- Each channel value is either a string (address/handle) or an object with details (especially for webhooks).

Webhook details (recommended fields):
- url (string): HTTPS endpoint
- method (string): Usually POST
- auth (string): How to authenticate (e.g., Bearer token; HMAC signature)
- format (string): Payload schema description
- headers (object, optional): Additional required headers
- signature (object, optional): Signature scheme (e.g., HMAC SHA-256 with shared secret; or `public_key` verification)

Example webhook payload format:
```json
{
  "message": "Short description of the request",
  "from": "agent@caller.example",
  "purpose": "support|scheduling|general",
  "priority": "normal|urgent",
  "context": {
    "thread_id": "optional-uuid",
    "related_urls": ["https://..."]
  }
}
```

4) Multi-Agent Configurations

Use `agents[]` to list specialized agents and define routing semantics:

Required per agent entry:
- name (string)
- handles (array of strings): Topics or intents (e.g., ["scheduling", "availability"])
- channel (string): The primary channel key to use for this agent
- id (string): The address/identifier for that channel (e.g., email address, webhook URL, or handle)

Example:
```yaml
agents:
  - name: "Calendar Agent"
    handles: ["scheduling", "availability", "rescheduling"]
    channel: email
    id: "calendar@example.org"
  - name: "Support Agent"
    handles: ["technical support", "bug reports"]
    channel: webhook
    id: "https://example.org/agent/support"
```

The body should explain:
- When to choose a specialized agent vs the general inbox
- Response time expectations per agent
- Any format specifics (e.g., attach iCal for scheduling)

5) Privacy Tiers

- Public: `/.well-known/agent-card` — minimal, safe-to-share channels and capabilities.
- Named/Professional: `/.well-known/agent-card/{name}` — more context for professional contacts.
- Private: `/{random-uuid}/agent-card.md` — private URL for trusted contacts.

Best practices:
- Expose fewer capabilities and channels at higher-discoverability tiers.
- Require stronger auth for sensitive operations (e.g., signature verification).

6) Discovery

- Well-known URL: `https://{domain}/.well-known/agent-card`
- Named variant: `https://{domain}/.well-known/agent-card/{name}`
- vCard extension: `X-AGENT-CARD:https://{domain}/.well-known/agent-card`
- Human-provided URL: When not discoverable by other means.

Discovery priority:
1) vCard pointer (most specific)
2) `/.well-known/agent-card` on the user’s domain
3) Ask the human for the URL

7) Routing Rules (Markdown Body)

The body should provide clear, action-oriented instructions:
- For scheduling: use Discord; accepts iCal attachments
- For urgent: email with "URGENT" in subject; response within 2 hours
- For support: POST to webhook with specific JSON schema
- Escalation: list types of requests escalated to a human
- Verification: describe OTP or signature checks for sensitive actions
- Response time expectations per channel

Bad example: “Use whatever channel you want.”
Good example: “For scheduling, use email calendar@example.org with an iCal attachment. For urgent matters, SMS +1 555 0100 with ‘urgent’.”

8) Security and Privacy

- Never publish secrets or tokens in the card. Use tokens that can be rotated, or require out-of-band verification.
- For webhooks, prefer HTTPS, verify signatures, and set rate limits.
- Do not log sensitive environment variables or API keys in any consuming system.
- Redact PII in logs; store only what is necessary to route and authenticate.

9) Versioning and Compatibility

- Current: `version: "1"`
- Future versions aim for backward compatibility. Consumers should gracefully ignore unknown fields.