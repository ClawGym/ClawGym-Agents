Tenant Onboarding Web Portal — Phased Plan and Major Workstreams

Summary
- Goal: Enable new customer tenants to self-serve onboarding in under 10 minutes, with secure SSO, correct role provisioning, compliant data handling, and integrations (billing, CRM, email) functioning reliably from day one.
- Constraints: 8-week timeline, small core team (FE 2, BE 2, Design 1, PM 1), zero tolerance for data loss or role escalation bugs, accessibility and auditability not optional.

Success Criteria
- New tenant can: sign up, verify email or SSO, add billing method, invite users, assign roles, connect CRM, and complete a guided setup checklist in ≤ 10 min.
- Multi-domain SSO tenants provision correctly (no domain-based assumptions).
- Data model supports invitations, roles, and tenant lifecycle states without hotfixes.
- Idempotent integration flows (webhooks, retries) verified pre-launch.
- WCAG AA compliance for core flows; analytics + audit trails in place.

Phase 1 — Discovery & Alignment (Week 1)
Workstreams
- Stakeholder interviews: sales, support, compliance, security.
- Define onboarding outcomes, metrics, and guardrails (non-negotiables).
- Role taxonomy: tenant admin, billing admin, member, viewer, invited user.
- Draft risk register and glossary (tenant, environment, region).
Deliverables
- Requirements brief v1
- Risk register v1
- Role definitions and lifecycle states
Dependencies
- None

Phase 2 — Architecture & Data Model (Weeks 1–2)
Workstreams
- Multi-tenant boundaries, identity flows (SAML/OIDC) and SCIM posture.
- Data model: tenants, users, roles, invitations, subscriptions, audit events.
- Eventing & idempotency strategy for integrations.
- ADRs for identity, roles, and data partitioning.
Deliverables
- ADR-001 Identity & RBAC
- ADR-002 Data model & partitioning
- Schema draft + migration plan scaffold
Exit Criteria
- Data model freeze v1 approved
Dependencies
- P1 role definitions and glossary

Phase 3 — UX/UI & Content (Weeks 2–4)
Workstreams
- Onboarding wizard IA and screen flows.
- Field list and validation rules (admin vs billing contacts, required docs).
- Component library selection and accessibility baseline (WCAG AA).
- Copy doc for labels, hints, error messages; localization plan stub.
Deliverables
- High-fidelity prototype
- Component checklist (a11y, states)
- Copy spec (field-level)
Dependencies
- P2 data model entities and role taxonomy

Phase 4 — Integrations (Weeks 3–5)
Workstreams
- SSO (SAML/OIDC) and SCIM (if feasible v1 or stub hooks).
- Billing (Stripe) — subscription, proration, invoice emails.
- CRM (HubSpot/Salesforce) sync for tenant metadata and lifecycle.
- Email (Postmark) for invites, verification; domain config steps.
Deliverables
- Integration runbooks per system
- Retry + idempotency strategy implemented and tested
- Staging credentials and fixture tenants
Dependencies
- P2 eventing strategy + P3 field list

Phase 5 — Data Migration & Tenant Seeding (Weeks 4–6)
Workstreams
- Migration plan (legacy tenants, normalized attributes, dedupe, mapping).
- Dry runs with anonymized samples; validation reports and rollback plan.
- Seed two pilot tenants with realistic data.
Deliverables
- Migration scripts + checksum/validation harness
- Rollback + backfill procedures
Dependencies
- P2 schema freeze v1
- P4 integration hooks available

Phase 6 — Security, Compliance & Observability (Weeks 5–6)
Workstreams
- Threat modeling for onboarding flows and role escalation.
- PII retention and data residency policy; encryption at rest and in transit.
- Audit trails for admin actions; dashboards + alerts for critical paths.
Deliverables
- Security checklist complete
- Compliance notes (PII retention, data export)
- Observability dashboards (signup funnel, errors, webhook retries)
Dependencies
- P2 ADRs, P4 integration events

Phase 7 — Pilot (Closed Beta) & Feedback (Weeks 6–7)
Workstreams
- Onboard two design partners with distinct identity models (single vs multi-domain).
- Track friction (support, analytics, logs) and triage into fix/after GA.
- Validate GA gating criteria (no P0s; P1s with workarounds).
Deliverables
- Pilot report and GA go/no-go matrix
Dependencies
- P5 seeded tenants, P6 monitoring

Phase 8 — Launch & Handoff (Week 8)
Workstreams
- Release plan with feature flags; backout plan defined and tested.
- Runbooks for support; training for sales and success.
- Handoff to ops with clear SLIs/SLOs for onboarding funnel.
Deliverables
- Launch checklist signed
- Ops handoff doc + training session
Dependencies
- P7 go decision

Key Dependencies and Known Branch Points
- Data model freeze in P2 affects P3–P5; mistakes multiply into UI, integrations, and migration.
- SSO/SCIM approach in P4 shapes role provisioning and support workload.
- Idempotency decisions affect billing, CRM sync, and email deliverability.
- Migration validation in P5 is irreversible in production without a well-tested rollback.

Non-Goals (v1)
- Full localization beyond English
- SCIM write-back to IdP (read-only or stub)
- Advanced tenant analytics beyond onboarding funnel