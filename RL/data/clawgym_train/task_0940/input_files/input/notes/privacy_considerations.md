# Privacy and Compliance — Progressive Profiling

Principles
- Collect only what you need for the stated purpose (data minimization).
- Make every optional field clearly optional and explain why you are asking.
- Link to the privacy policy near the form and avoid dark patterns.
- Provide a path to skip and continue without penalty.
- Avoid collecting sensitive categories unless strictly necessary.
- Give users control to view, edit, or delete optional profile data at any time.

Consent and lawful basis
- Record timestamped consent scopes (e.g., ‘marketing_emails’, ‘personalization’).
- Separate product-essential processing from marketing; do not bundle consent.
- Use granular toggles rather than one blanket checkbox for unrelated purposes.
- Store who, when, and how consent was captured, including UI context.
- Honor withdrawal of consent immediately and propagate to downstream systems.

Purpose limitation
- Annotate each attribute with a purpose tag and enforce usage boundaries.
- If purpose changes, re-collect consent and communicate clearly to users.
- Do not repurpose optional profile data for advertising without explicit opt-in.

Transparency
- Place a concise explanation next to each optional field: “Used to personalize templates.”
- Link “Learn more” to the specific section of the privacy policy.
- Publish a data dictionary outlining optional attributes, purposes, and retention.

Retention and deletion
- Set retention periods for optional attributes and purge when no longer needed.
- Respect account deletion by erasing optional attributes and associated prompts.
- For inactive accounts, consider staged deletion: archive → erase.

Access and portability
- Provide export of profile data in a common format upon request.
- Log access to sensitive optional attributes and review periodically.

Regional considerations
- Handle age gating and parental consent where required.
- Localize consent language and default settings to regional expectations.

Security
- Encrypt optional attributes at rest where feasible.
- Limit access via role-based permissions; audit reads and writes.
- Avoid storing raw free-text when categorical options suffice.

User experience commitments
- Do not gate activation on optional attributes.
- Do not nag; implement cool-down after a skip.
- Offer value when asking (e.g., “We’ll recommend a better starter template.”)