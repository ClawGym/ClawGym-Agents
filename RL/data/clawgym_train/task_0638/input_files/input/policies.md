# Northwind Policies and Standards (Extract)

Policy IDs referenced below are mandatory for all DevTools rollouts, including bcc.

1. Security Policy (SP-01)
- MFA is mandatory for any system that can modify production or distribute artifacts.
- Enforce role-based access control and the principle of least privilege.
- All binaries must be signed; unsigned executables are prohibited in production.
- Secrets must be stored in Vault; no secrets in code, images, or configs.

2. Data Protection (DP-04)
- Encrypt data at rest and in transit.
- Logs must not contain PII; apply redaction by default.
- TLS 1.2+ for any applicable transport.

3. Logging & Monitoring (LM-02)
- All production workloads must forward logs to Datadog via Fluent Bit.
- Standard log file path prefix: /var/log/devtools/.
- Retain standard logs for 30 days; retain security-relevant logs for 90 days.
- Provide a runbook for interpreting logs and responding to alerts.

4. Change Management (CM-03)
- All changes require a change ticket (prefix CHG-) and at least two code reviews.
- Approved maintenance windows: Tuesday and Thursday 18:00–20:00 PT.
- Every change must include a documented rollback plan and tested rollback steps.

5. Access Control (AC-05)
- All distributions must enforce RBAC for who can publish and promote artifacts.
- Production clusters follow “deny by default” network policy; exceptions require tickets.

6. Performance Monitoring (PM-07)
- Define baseline performance metrics before production rollout.
- Monitor P95 CLI invocation latency and memory usage where applicable.
- Set alerts if error rate exceeds 1% over a 15-minute window.

7. Tooling Standards (TS-08)
- Prefer internal package repositories (apt.northwind.local, brew.northwind.local).
- Container images must come from the approved registry and be signed.
- SBOM (SPDX or CycloneDX) must be attached to released artifacts.
- No SUID/SGID bits in distributed binaries without CISO exception.

8. Open Source Compliance (OS-09)
- Maintain a NOTICE and LICENSE file where required.
- Record third-party dependencies in SBOM; approve licenses through Legal if needed.

9. Incident Response (IR-06)
- Provide a 5-step debugging runbook for triage and resolution.
- Assign ownership for alerts and incident coordination.
- Post-incident reviews are required within 5 business days.

10. Documentation (DOC-02)
- Document Quickstart steps and operational runbooks.
- Maintain a migration plan with a pre-migration checklist.
- Keep a change log aligned to released versions and tickets.

Appendix: Clarifications for bcc
- bcc is a local CLI documentation tool with no network dependencies at runtime.
- Despite low runtime risk, distribution pathways (repos, CI, registry) must comply with SP-01, CM-03, TS-08.
- MFA is enforced on Okta (SSO), artifact repositories, CI/CD, and cluster access—not within bcc itself.