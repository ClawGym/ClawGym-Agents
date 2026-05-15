# Risk, Compliance, and Change-Management Constraints

Compliance posture:
- SOC 2 Type II in force; change management and access controls audited quarterly.
- GDPR compliance; DPIA required for high-risk processing or new vendors handling EU personal data.
- PCI scope: SAQ A (hosted fields via Stripe); no card data may pass through our systems or LLM prompts.

Data protection & privacy:
- Prohibited: sending PII, payment data, or customer confidential data to third-party LLMs without DPA and data residency assurances.
- Redaction required for logs and training data; store minimal data.
- Data residency: US primary; EU mirror for applicable customers.
- All automations must use least-privilege service accounts with Okta SSO when available.

Vendor risk:
- All new vendors require security review (questionnaire + DPA), vulnerability assessment, and legal approval.
- Preferred vendors: Google Cloud, HubSpot, Zendesk, DocuSign, Stripe, QuickBooks Online, Okta, Vanta.
- Use existing platforms’ native APIs and webhooks when possible before adding new tools.

Change management:
- Every automation must have:
  - Jira RFC with design, data flows, and rollback plan.
  - Staging/sandbox validation (e.g., HubSpot sandbox, Stripe test mode, DocuSign demo).
  - Monitoring and alerting with clear owners.
  - Rollback within 30 minutes for high-impact workflows.
- No direct writes to production databases; use versioned services and audited APIs.

Operational constraints:
- Rate limits: respect HubSpot, Zendesk, Stripe, and QBO API limits; include backoff/retry.
- Email compliance: no automated outbound emails without approved templates from Legal/Marketing; unsubscribe handling required.
- Support SLAs: ticket priority changes must preserve audit history in Zendesk.
- Security: access provisioning must be auditable via Okta and Vanta; approvals required for privileged roles.

Tooling guidance:
- Prefer in-platform automation (HubSpot workflows, Zendesk triggers/macros, Okta Workflows, Google Apps Script) before custom code.
- Zapier/Make allowed only after security review; store tokens in 1Password; rotate every 90 days.
- All scripts must run under a service account, not personal accounts.

Assumptions for ROI:
- Use company_profile.json hourly_cost if provided; otherwise default to $36/hr.
- Savings must consider license/implementation costs and compliance overhead (security reviews may add 1–2 weeks for new vendors).
- Quick wins should leverage existing stack and sandboxes to minimize risk.