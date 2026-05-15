Product: OpsForge

Core capabilities
- Cross‑tool orchestration: Build workflows that span CRM, HRIS, ITSM, finance, and collaboration tools without brittle point‑to‑point zaps
- AI Router: Learns routing patterns and applies policy rules to assign tasks to people or systems; supports fallback to deterministic paths
- Human‑in‑the‑loop: Approvals and task assignments inside Slack and email with SLAs, auto‑reminders, and escalation
- Policy graph: Define approver eligibility (role, spend thresholds, geography), dual control, and segregation of duties
- Observability: Run history with step‑level timing, retries, diffs on data mutations, and immutable audit logs
- Connectors: 40+ launch connectors including Salesforce, HubSpot, NetSuite, Workday, BambooHR, Okta, Google Workspace, Slack, Jira, Asana, ServiceNow, Snowflake, Postgres, S3
- Security & compliance: SSO/SAML, SCIM, role‑based access, least‑privilege tokens; SOC 2 Type II in progress (controls mapped and audited by Q3)
- Data: US/EU data residency options; encrypted at rest and in transit; field‑level redaction and vault for secrets
- Deployment: Fully managed SaaS; optional private connectors for restricted networks

Out‑of‑the‑box playbooks
- Employee onboarding/offboarding (HRIS ↔ Okta ↔ IT tickets ↔ device provisioning)
- Lead lifecycle QA and dedupe (CRM ↔ enrichment ↔ routing)
- Vendor onboarding and spend approvals (Intake form ↔ finance approvals ↔ ERP vendor record)
- Credit memo and discount approvals (CRM ↔ finance) with dual control
- Access reviews and quarterly user access recertification (Okta ↔ managers ↔ ITSM)

Differentiators vs. status quo
- Policy‑aware routing + audit‑grade logs (vs. brittle zaps and email trails)
- Approvals where work happens (Slack/email) with clear SLAs (vs. hidden inside ticketing)
- Weeks to value using prebuilt, cross‑tool playbooks (vs. months‑long iPaaS projects)
- Human‑in‑the‑loop by design, not a bolt‑on afterthought

Pricing and packaging
- Standard: $2,000/month, up to 50 active workflows, includes 2 workspaces and SSO — Average contract value (ACV): $24,000/year
- Business: $4,000/month, up to 150 active workflows, advanced RBAC and data residency — Typical ACV: $48,000/year
- Enterprise: custom, unlimited workflows, private connectors, premium support
- Optional implementation: $5,000 fixed for guided pilot → production
- Typical add‑ons: additional workspaces, premium connectors (e.g., SAP), premium support

Sales motion and cycle
- Selected motion: Sales‑led with content assist
- Why: Mid‑market ACV averages $24,000/year; buyers require security review, pilot proof, and stakeholder alignment
- Free 30‑day guided pilot with CSM and solution architect; success plan defined up front (2 measurable outcomes)
- Typical cycle: 45–75 days including security and legal
- Key artifacts: security one‑pager, SOC 2 controls mapping, ROI calculator, case studies

Buyer and objections
- Decision maker: Head/Director of Operations, VP RevOps, COO (smaller firms), Finance Ops for spend approvals
- Influencers: Operations Managers, Systems Admins, BizOps ICs, IT for SSO/security
- Objections and responses:
  - “We have Zapier/Make.” → Those tools are great for simple single‑app tasks. OpsForge handles cross‑tool processes with policy graphs, human approvals, and audit‑grade logs.
  - “Approvals live in ServiceNow.” → We integrate with ServiceNow and pull approvals into Slack/email to reduce cycle time while preserving governance.
  - “AI is risky.” → AI Router never bypasses policy; every AI decision has a deterministic fallback and a human approval step when required.

Evidence (beta)
- Northbridge Logistics: 43% faster onboarding; 18 hours/week manual effort removed
- Finovo Capital: vendor approval cycle time cut from 5.2 days to 1.9 days; audit time down 12%
- Acme Bio: quarterly access review completion rate improved from 78% to 95% within window

Implementation
- Time to first value: median 12 days
- Typical initial scope: 1–2 cross‑tool workflows with 2 approver paths
- Data migration: none; we orchestrate systems of record rather than replace them