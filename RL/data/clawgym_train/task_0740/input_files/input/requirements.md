Vendor Risk Assessment Assistant — Requirements

Overview
- Purpose: Assist risk operations with evaluating third-party vendors for compliance, data protection posture, and ongoing risk monitoring. The assistant analyzes structured vendor profiles and assessment requests, validates control evidence against policy maps (including GDPR), classifies risk levels, and triggers escalation workflows when thresholds are exceeded.
- Compliance context: Handles PII and must respect GDPR constraints; ensure auditability and replay for regulatory review.

Fixed Identity (must be honored)
- agent_id: agent.risk.vendor_assessor
- agent_version: 1.2.0
- status: draft
- owner.owner_id: risk-ops-team
- owner.owner_kind: organization
- meta.title: Vendor Risk Assessor
- meta.lang: en
- meta.tags: risk, vendor, compliance (additional suggestions: gdpr, pii, audit, escalation)
- meta.description (guidance): One-paragraph scope that clearly explains vendor risk assessment, decision boundaries, and when to hand off. It must include the words: “escalation”, “PII”, and “GDPR”.

Task Domains and Capabilities
- task_domains (must include): risk, compliance
- optional domain: security (appropriate due to control evaluation and policy mapping)
- capability_tags (must include at least): analyze, classify, validate, escalate
- recommended additional capabilities: summarize, generate_text, compare, recommend, notify

Input and Output Envelopes (use exactly these)
- Input Envelopes:
  - env.risk.assessment_request_v1
  - env.risk.vendor_profile_v1
- Output Envelopes:
  - env.risk.assessment_report_v1
  - env.risk.escalation_request_v1
Envelope naming notes: Follows env.<domain>.<action>_v1 convention; all mapped to the risk domain and aligned to vendor assessment workflows.

Runtime and Connectors
- runtime_binding_ref: runtime.cloud.generic_v1
- connectors: Provided in connectors.json; include all listed connectors in the final contract.

Policy and Guardrails
- policy_profile_ref: policy.risk.vendor_assessment_guardrails_v1
- Policy expectations:
  - Access control: restrict PII use to assessment purposes; no persistence beyond retention policy
  - GDPR: data minimization, purpose limitation, and support for data subject rights workflows
  - Escalation: mandatory when risk score >= 8/10, missing mandatory controls (e.g., DPA absent), or suspected regulatory violations
  - Forbidden actions: exporting raw PII outside approved systems; making binding legal decisions without human approval

Observability (required)
- compact_required: true
- semantic_required: true
- otel_correlation_required: true
- required_artifacts: episode, decision_log, audit_trail (optional addition: summary)
- Notes: Ensure decision rationale is captured for regulator audits and internal QA.

Determinism & Limits (preferences)
- determinism_controls:
  - seed_required: true
  - replay_supported: true
- limits:
  - max_tokens: 6000
  - max_duration_ms: 150000
  - max_tool_calls: 8

Risk and Escalation Guidance
- Trigger escalation if:
  - High inherent risk vendor with inadequate compensating controls
  - Control failures in encryption at rest/in transit for PII
  - Absence of DPA or unacceptable SCCs for cross-border transfers
  - Any indication of recent breach without documented remediation
- Escalation destination: create a Jira ticket with a summary, risk score, control gaps, and recommended next actions.

Data Handling & Privacy Notes
- PII categories expected: contact details, business identifiers; avoid unnecessary collection
- Apply data minimization in all outputs; redact non-essential fields
- Ensure all logs avoid full raw PII exposure while preserving auditability (store pointers/hashed references where supported)

Operating Assumptions
- The assistant does not enforce live policy; it interprets vendor evidence against defined policy maps and flags discrepancies
- Human approval required for final vendor onboarding decisions
- The envelope schemas and policy profiles exist or will be authored separately and referenced by this contract

Success Criteria
- Clear, auditable assessment reports
- Correct, timely escalations
- Compliance with GDPR and internal data handling policies
- Deterministic and replayable assessments for QA and audits