# Security Announcement: TLS Modernization and Certificate Rotation

Date: 2026-04-15

To continue aligning with industry best practices and to enhance the security of our platform, we will be performing TLS updates and certificate maintenance across our public endpoints.

What’s changing:
- Deprecation of legacy protocols: TLS 1.0 and TLS 1.1 will be disabled starting May 20, 2026.
- Minimum protocol: TLS 1.2 will be the minimum required; TLS 1.3 is supported where available.
- Certificate rotation: We will rotate leaf certificates for the following hostnames between May 18–22, 2026:
  - api.acmecloud.example
  - console.acmecloud.example
  - files.acmecloud.example
- Certificate authorities: We will continue to use publicly trusted CAs; intermediates may change without notice as part of routine security operations.
- SAN consolidation: Some regional SAN entries will be consolidated under *.acmecloud.example to simplify management.

Expected impact:
- No customer action is required for modern clients that already support TLS 1.2+ and SNI.
- We anticipate no downtime; brief connection resets (<30 seconds) may occur during rolling updates.
- Partners using strict certificate pinning, outdated trust stores, or non-SNI clients may experience connection errors until configurations are updated.

Recommendations:
- Ensure clients support TLS 1.2 or higher and Server Name Indication (SNI).
- Avoid hardcoding specific intermediate CAs or leaf certificate fingerprints. If certificate pinning is required, prefer pinning to the CA public key or use a pinset with multiple valid keys.
- Update any allowlists to include *.acmecloud.example if relying on SAN-specific host entries.

Support:
If you have questions or foresee potential disruptions, contact support through your account portal. We reserve the right to adjust timelines as part of our continuous security improvement process.

— AcmeCloud Security Team