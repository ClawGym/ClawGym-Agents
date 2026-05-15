# Constraints and Policies

These constraints are non-negotiable and must be respected in all onboarding documentation and operations for the Arbitrage Finder service.

- Network egress: Production workers may call only allowlisted market data endpoints; no access to unknown domains.
- Credentials: Arbitrage Finder core workflows require no external API keys; never hardcode secrets; use role-based access with short-lived tokens when needed.
- Change management: Two-person code review minimum; staged rollout with a 5% canary; rollback must be possible within 15 minutes.
- Resource limits: p95 CPU utilization ≤ 70%; memory watermark ≤ 75%; per-pod limits max 2 vCPU and 4 GiB RAM unless approved.
- Logging: No PII in logs; sanitize all inputs; production debug logging is disabled except during incidents with approved temporary overrides; log retention 14 days.
- Dependency policy: Pin versions; no experimental or unvetted features in production; maintain SBOM and weekly vulnerability scans.
- Observability: Mandatory health checks, readiness probes, and baseline dashboards deployed before any production release.
- Security posture: Principle of least privilege; MFA for all administrative access; restrict inbound/outbound ports to the minimum required.
- Compliance and audit: All configuration changes must be recorded; time sync is enforced via NTP; maintain immutable audit trails for deployments and incidents.
- Environment compatibility: Linux and bash must be supported; avoid vendor-specific commands in runbooks beyond what is essential to operate the service.
- Data handling: Encrypt data in transit and at rest; backups must be tested quarterly; recovery procedures documented and practiced.