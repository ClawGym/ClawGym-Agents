# Security and Licensing Guardrails

This document defines the mandatory controls for adopting AI assistant extensions in Waypoint Systems.

1) Licensing Policy
- Allowed licenses: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause.
- Prohibited licenses: GPL, AGPL, LGPL, SSPL, and any viral/copyleft or proprietary EULAs that restrict internal use.
- All transitive dependencies must comply with the same policy; no exceptions without legal approval.
- A machine-readable license report must be produced and attached to the approval record.

2) Supply Chain and Provenance
- All dependencies must be version-pinned; lockfiles are required.
- Prefer artifacts with SLSA provenance or equivalent signed attestations.
- SBOM must be generated for evaluation and retained for audits.
- Packages with unmaintained status (no commits in 12 months) or single maintainer without backup require additional risk review.

3) Security Controls
- Static analysis must run before POC completion; high/critical findings must be remediated or the candidate is rejected.
- Dependency vulnerability scanning must show no critical or high issues; medium issues require documented mitigations.
- Network egress: CI and canary environments are allowlist-only; extensions must operate with telemetry disabled or strictly opt-in.
- Secrets: No embedding or hardcoding; all secrets must be loaded via Vault or environment injection and never logged.
- Data handling: No production PII in POC or discovery. Staging must use masked data. Redaction is mandatory for logs and LLM prompts.

4) Runtime and RBAC
- Default to read-only operations in discovery and POC.
- Kubernetes access must follow least privilege; no cluster-admin in canary; namespace-scoped and time-bound RBAC is required.
- Database operations must enforce RLS patterns and principle of least privilege; migrations must be peer-reviewed.

5) Operational Readiness
- Feature flags must gate all new capabilities. Defaults are off.
- Rollback plans must be documented, automated where possible, and rehearsed prior to canary.
- Monitoring must include latency, error rate, and business impact metrics with thresholds and alerts.
- Clear ownership, on-call rotation coverage, and escalation paths are required for each extension.

6) Approval Workflow
- Stage-gated approvals: Security and Platform sign-off after Discovery; Security, Platform, and Product sign-off after POC; CAB approval before Production.
- Evidence bundle includes: static analysis results, vulnerability scan, SBOM, license report, RBAC review, data-handling assessment, and monitoring plan.
- Any deviation from these guardrails requires documented risk acceptance by the Security lead and Product owner.

7) Post-Deployment Monitoring
- Baseline metrics must be captured prior to canary. Monitoring and alerting are enforced at canary and production.
- Weekly review of incidents, near-misses, and regressions during the first 30 days.
- Automatic rollback triggers must be defined for error-rate spikes, latency SLO breaches, or security policy violations.

8) Audit and Records
- All approvals, reviews, and changes must be recorded in the change management system.
- Keep artifacts (reports, SBOM, scan results, checklists) for at least 24 months for SOC 2 and ISO 27001 audits.

9) Decommission and Rollback
- Extensions must support safe disablement via feature flags and configuration toggles.
- Rollback playbooks must detail steps to revert to the last known good state, including data migrations, RBAC changes, and configuration cleanup.
- Post-rollback validation must confirm return to baseline metrics and policy compliance.