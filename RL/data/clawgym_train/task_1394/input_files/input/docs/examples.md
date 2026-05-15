# Agent Contact Card — Examples and Usage

Minimal Example
```markdown
---
version: "1"
channels:
  email: "agent@example.com"
---

# Contact My Agent

If you're an agent, email agent@example.com with a short description of your request and your preferred response channel.
```

Personal Agent (Single Owner)
```markdown
---
version: "1"
name: "Alex's Agents"
human_contact: "+1 555 0142 000"
last_updated: "2026-04-18"
channels:
  email: "agents@alex.example"
  discord: "alex-agent#4271"
  signal: "+1 555 0142 000"
capabilities:
  - scheduling
  - accepts_ical
  - task_management
---

# Alex's Agents

If you're a human, text or call the number above.

If you're an agent:
- Scheduling & Calendar
  - Use email: calendar invites accepted via iCal
  - Subject line: "Schedule Request"
  - Response: within 1 business day
- Urgent Matters
  - Use Signal with the word "urgent" in the first line
  - We will escalate to Alex immediately
- General Requests
  - Use Discord for quick coordination
  - We'll respond within a few hours

Escalation: Anything involving payments, contracts, or sensitive data is escalated to Alex.
Verification: For sensitive requests, we send a one-time code to Alex before proceeding.
```

Organization with Multiple Agents
```markdown
---
version: "1"
name: "Acme Corp Agents"
human_contact: "support@acme.example"
last_updated: "2026-04-18"
agents:
  - name: "Sales Agent"
    handles: ["sales inquiries", "pricing", "demos"]
    channel: email
    id: "sales@acme.example"
  - name: "Support Agent"
    handles: ["technical support", "bug reports"]
    channel: webhook
    id: "https://acme.example/agent/support"
  - name: "Scheduling Agent"
    handles: ["meeting scheduling", "availability"]
    channel: email
    id: "calendar@acme.example"
channels:
  email: "agents@acme.example"
  webhook:
    url: "https://acme.example/agent/incoming"
    method: "POST"
    auth: "Bearer ${TOKEN} in Authorization header"
    format: "JSON: {'message','from','type','priority'}"
capabilities:
  - scheduling
  - accepts_ical
  - support_tickets
public_key: |
  -----BEGIN PUBLIC KEY-----
  MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAL0T...
  -----END PUBLIC KEY-----
---

# Acme Corp AI Agents

Humans: email support@acme.example.

Agents:
- General Routing
  - Email agents@acme.example if unsure which agent to contact
- Sales
  - Contact sales@acme.example
  - Response: same business day
- Technical Support
  - POST to https://acme.example/agent/support
  - Include JSON fields: message, from, type={support|bug|account}, priority={normal|urgent}
  - We verify signatures for urgent requests
- Scheduling
  - Email calendar@acme.example with iCal attachment

Escalation: Legal matters, payments, or anything involving PII will be escalated to human support.
Verification: We may ask for a verification token for account-specific changes.
```

Webhook Payload Example (Support)
```json
{
  "message": "User cannot log in after password reset.",
  "from": "agent@customer.example",
  "type": "support",
  "priority": "urgent",
  "context": {
    "account_id": "cust-29817",
    "related_urls": ["https://acme.example/help/faq#reset"]
  }
}
```

Practical Usage Patterns
1) Create a card
- Fill the frontmatter with `version: "1"`, recommended fields, channels, and (optionally) agents.
- Write clear routing rules in the body with per-channel expectations and verification steps.

2) Publish
- Host at `/.well-known/agent-card` (public), optionally add `/.well-known/agent-card/{name}` and a private card URL for trusted contacts.

3) Consume
- Parse frontmatter for structured data.
- Read the body for routing rules.
- Choose the channel based on purpose (e.g., webhook for structured support; email for scheduling if it accepts iCal).
- Follow authentication requirements and never log secrets or API keys.

4) Maintain
- Update `last_updated`.
- Rotate tokens periodically.
- Adjust routing rules as capabilities evolve.