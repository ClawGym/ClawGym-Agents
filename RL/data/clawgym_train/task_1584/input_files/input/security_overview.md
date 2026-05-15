# DocuFlux AI — Security Overview (FluxExtract)
Last updated: 2026-03-28

## Certifications & Audits
- SOC 2 Type I: Achieved on 2026-03-10. Report available under NDA.
- SOC 2 Type II: Audit period in progress; target report by Q4 2026.
- ISO 27001: Not certified.
- HIPAA: No standard BAA; Enterprise evaluation on request.
- PCI-DSS: Not applicable (no cardholder data processed within FluxExtract).

## Architecture & Hosting
- Cloud provider: AWS (primary regions: us-east-1, eu-west-1 for EU residency).
- Network segmentation with private subnets for core services; public endpoints via AWS ALB with WAF.
- Secrets stored in AWS Secrets Manager; automatic rotation for database credentials.

## Encryption
- At rest: AES-256 (RDS, S3, EBS). Keys managed by AWS KMS. Customer-managed keys (CMK) available on Enterprise tier.
- In transit: TLS 1.2+ enforced; HSTS enabled; strong ciphers only (no RC4/3DES).
- Document encryption: Objects in S3 are server-side encrypted (SSE-KMS).

## Identity & Access Management
- SSO: SAML 2.0 / OIDC supported for Enterprise (Okta, Azure AD, Google Workspace).
- MFA: Enforced for internal admin and production access; customers can enforce MFA at workspace level.
- RBAC: Role-based access with least privilege defaults; audit logs for admin actions retained 12 months.
- Session management: 12-hour max session; inactivity timeout 30 minutes.

## Secure SDLC
- Code reviews required for all changes; branch protection rules in Git.
- Static analysis, dependency scanning, and secret detection in CI/CD.
- Infrastructure as Code (Terraform) with peer review.
- Change management includes staged rollouts and canary deployments.

## Vulnerability Management & Testing
- Penetration testing: Third-party semi-annual tests; executive summary available under NDA within 30 days of request.
- Vulnerability scanning: Weekly scans; critical patches prioritized within 7 days; highs within 30 days.
- Bug bounty: No public program; responsible disclosure at security@docuflux.ai with 5 business day triage SLA.

## Incident Response & Monitoring
- 24/7 on-call rotation with PagerDuty; centralized logging and SIEM alerts.
- Incident response plan tested twice yearly via tabletop exercises.
- Breach notification: For confirmed incidents impacting customer data, notify administrative contacts within 72 hours.
- Post-incident reports provided within 10 business days of incident closure.

## Data Segregation & Customer Controls
- Multi-tenant logical segregation via per-tenant scoping and access tokens.
- Optional dedicated EU data residency (eu-west-1) for Professional/Enterprise tiers.
- Export controls: Self-serve data export via API and admin UI.

Known Gaps / In-Progress Improvements
- SOC 2 Type II report not yet available (target Q4 2026).
- No public bug bounty program.
- No formal red-team exercises to date (planned 2027).