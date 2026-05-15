# Compliance Policy Summarization Assistant — Product Brief

Purpose
- Help the Compliance team rapidly understand long-form policy PDFs (external and internal).
- Extract obligations, deadlines, and risks into structured data.
- Deliver an executive summary + a ready-to-use implementation checklist.
- Operate safely with untrusted PDFs using isolation and strict sanitization.
- Keep spend predictable with approval gates for higher-cost actions.

Scope
- Inputs: Untrusted PDF policy documents (up to ~20MB / ~300 pages).
- Context: No external network calls by default. Use only local parsing and internal references.
- Supported document types: regulatory policy PDFs, corporate policy PDFs, legal guidance PDFs.
- Language: English documents only for v1.
- Delivery format: 
  1) EXEC_SUMMARY.md (≤ 500 words, plain English; audience = exec/non-legal)
  2) CHECKLIST.md (actionable steps with owners, dependencies, and due dates)
  3) obligations.json (machine-readable; schema v1.0 below)
  4) deadlines.json (normalized dates with assumptions recorded)
  5) risks.json (identified risk statements with severity and rationales)

Obligation Schema (v1.0)
- obligation_id: string (stable, unique per document, e.g., "OBL-2026-0001")
- actor: string (e.g., "Data Protection Officer", "IT Security", "Compliance")
- action: string (imperative phrasing, e.g., "Maintain records of processing activities")
- trigger: string (event or condition that triggers the obligation)
- due_date: string (ISO 8601 date, e.g., "2026-05-15"; specify timezone assumption)
- recurrence: string|null (e.g., "annual", "quarterly", or null)
- penalty: string|null (financial or operational consequence if specified)
- risk_level: string ("low" | "medium" | "high" | "critical")
- evidence_citations: array of strings (policy sections/pages that justify extraction)
- source_page: integer (page where the obligation primarily appears)
- notes: string (clarifications, assumptions, ambiguity flags)

Deadlines Normalization
- All extracted dates must be normalized to ISO 8601 (YYYY-MM-DD).
- Timezone assumption: UTC unless document explicitly states a timezone (record this assumption).
- Ambiguity handling: If a date is relative ("within 30 days"), convert to a relative expression with anchor notes; include the raw phrase.

Checklist Structure
- Title: "Implementation Checklist"
- Sections by responsible group (Compliance, Legal, IT Security, Data Engineering, HR, etc.).
- Each item includes: short title, description, owner, due_date (ISO), priority (P0/P1/P2), dependencies (list of other items), evidence link (if applicable).

Non-Functional Requirements
- Privacy: Do not store or expose personal data. If PII is encountered, redact before any inter-agent transfers.
- Determinism: Use a stable output schema and record schema version ("1.0").
- Logging: Keep minimal, sanitized logs of processing steps without document content.
- No external services by default: All research and validation use locally available materials or embedded document content. Federated peer review is manual/opt-in.

Orchestration Patterns (required)
- Security Proxy: Untrusted PDF parsing must run in a blast-shielded proxy with minimal context, strict tool whitelist (PDF text extraction only), and output schema validation prior to returning results. Enforce a per-spawn cost cap defined in cost_prefs.yaml.
- Researcher Specialists: Run three lenses (optimist, pessimist, pragmatist). Each lens must validate claims against at least 3 independent passages/sections within the document and/or internally stored reference summaries. Provide credibility scoring and cite evidence locations.
- Phased Implementation: Architect → Coder → Reviewer pipeline. The architect defines IMPLEMENTATION_PLAN.md (interfaces, schemas, gates). The coder implements parsing, extraction, and normalization. The reviewer validates against the quality rubric and risk mitigations.

Acceptance Criteria
- Executive summary ≤ 500 words, structured with bullets and short paragraphs, includes top 5 obligations and top 5 risks with their implications.
- obligations.json, deadlines.json, risks.json validate against the declared schema and include source citations (page numbers/sections).
- Checklist includes at least one actionable item per major obligation with ISO due dates or clear relative deadlines.
- Quality rubric: Minimum per-dimension score ≥ thresholds defined in the quality rubric; overall pass condition must be met before delivery.
- Risk alignment: Explicit mapping from known risks in risk_registry.json to implemented mitigations.

Operational Constraints
- Costs and approvals must honor cost_prefs.yaml.
- Approval is required if any subagent’s expected cost exceeds the approval_threshold.
- Security proxy must not receive any secrets or internal paths. Only pass the necessary PDF bytes (or chunked text), extraction instructions, and the output schema.

Definition of Done (v1)
- Orchestration plan produced with agents and safeguards.
- Templates documented for the three patterns with approval gate rules.
- Quality rubric formalized with 8 dimensions.
- Peer review package description (sanitized, structured, severity-tagged).
- A dry-run example on a sample policy shows correct schema outputs and passes the quality rubric.

Notes and Assumptions
- Default timezone: UTC (document overrides when explicitly stated).
- If sections conflict, capture contradiction notes and expose them in the evidence field.
- All file outputs should be plain text or JSON; do not embed binary data.

Change Log Expectations
- Version each output schema with semver (starting at 1.0).
- Document any changes to schema or approval gates in the plan and in a CHANGELOG note appended to EXEC_SUMMARY.md for internal review.

Contact
- Compliance Lead: Dana Romero
- Legal Counsel: Alex Nguyen
- Security Engineering: Priya Shah

---

Please refer to input/cost_prefs.yaml for budget and approval thresholds and to input/risk_registry.json for prioritized risks and mitigation alignment.