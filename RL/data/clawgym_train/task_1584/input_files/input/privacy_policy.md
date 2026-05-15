# DocuFlux AI — Privacy & Data Handling (FluxExtract)
Last updated: 2026-03-20

## Role & Scope
- DocuFlux acts as a data processor for Customer Content processed by FluxExtract.
- Customer is data controller. DocuFlux processes data per written instructions (MSA/DPA, product configuration).

## Data Residency & Transfers
- Default residency: United States (AWS us-east-1).
- EU Residency Option: Available in AWS eu-west-1 for Professional/Enterprise tiers; data processed and stored in-region.
- Cross-border transfers: Where applicable, rely on EU Standard Contractual Clauses (SCCs) and supplementary measures.

## Sub-Processors
- AWS (hosting, storage) — US/EU regions based on selected residency.
- SendGrid (transactional email) — US.
- Sentry (error monitoring) — US, with PII scrubbing enabled.
- PostHog (product analytics) — EU data center for EU tenants; US for others; collects event metadata only.
- Stripe (billing) — US/EU depending on payer location; no card data processed in FluxExtract.
- Third-party LLM provider for inference (US/EU regional endpoints); see “AI & Training”.

A complete list is available upon request and is updated at least quarterly. Customers are notified at least 30 days prior to material changes where required.

## Retention & Deletion
- Customer documents: Retained for the active term to support processing and reprocessing workflows.
- Deletion timelines:
  - Upon customer-initiated deletion request: purge within 7 days from hot storage; backups overwritten within 60 days.
  - Upon contract termination: purge within 30 days from hot storage; backups overwritten within 60 days.
- Application logs: 90 days retention by default.
- Audit/admin logs: 12 months retention.
- Model telemetry (aggregate, de-identified): 30 days.

## Data Access & Portability
- Export via API and admin UI (JSON/CSV). Bulk exports for offboarding available within 10 business days.
- Data subject requests: Supported for access, correction, deletion; typical response within 30 days.

## Privacy Compliance
- GDPR: Processor commitments via DPA with SCCs; supports data subject rights; maintains Records of Processing.
- CCPA/CPRA: Service provider commitments; no sale or sharing of Customer Content.
- Children’s data: Not intended for processing of data of children under 16; customers responsible for lawful basis.

## AI & Training
- Foundation model training: Customer Content is NOT used to train third-party foundation models by default.
- Quality improvement: Aggregated telemetry and de-identified samples may be used to improve service quality; customers may opt out at workspace level.
- Third-party LLM retention: Provider may retain prompts and outputs for up to 30 days for abuse monitoring; content is excluded from training datasets by default per provider commitments (as contracted).
- Customer can set “strict no-retention” mode for Enterprise, which routes to non-retaining endpoints (may impact latency).

## Security of Processing
- Encryption: AES-256 at rest; TLS 1.2+ in transit.
- Access controls: Role-based access; principle of least privilege; MFA enforcement available.
- Data minimization: Configurable redaction for sensitive fields during processing.

## Contact & DPA
- Data Protection Officer: dpo@docuflux.ai
- Security Contact: security@docuflux.ai
- DPA available upon request; includes SCCs and technical measures appendices.

Known Considerations / Customer Actions
- Default analytics and de-identified telemetry are enabled; consider enabling workspace-level opt-out if policy requires.
- EU residency requires explicit enablement on paid tiers; defaults to US if not configured.
- Third-party LLMs may retain data up to 30 days unless “strict no-retention” is enabled (Enterprise feature).