# Security

We designed NebulaDrive with a defense-in-depth approach that starts on the client and extends through our services.

Default encryption algorithm: AES-256-GCM with per-file keys and envelope encryption.

## Key Management
- Per-file data keys are generated client-side and wrapped (enveloped) by a workspace master key.
- Customer-managed keys (CMK) are supported via KMS integration on supported clouds.
- Rotations: master keys can be rotated without re-encrypting file data.

## Access Control
- Role-based access control (RBAC) with fine-grained permissions.
- SSO/SAML 2.0 and SCIM provisioning supported.

## Network Security
- All transport uses TLS 1.2+ with modern cipher suites.
- WebSockets are authenticated via short-lived tokens with rolling refresh.

## Auditing
- Immutable audit logs for access and administrative actions.
- Export integrations for SIEM platforms.