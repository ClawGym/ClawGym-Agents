# TOOLS — Configuration (pre-refactor)

Tooling Summary
- Backup/Restore: Node.js scripts using fs, path, crypto
- Validation: SHA-256 hashing and manifest checks
- Egress Scan: Optional (Python tool), not part of backup flow

Local Settings
- Backup root: ./backups
- Named backup root: ./backups/named
- Hash algorithm: SHA-256
- Concurrency: 1 (sequential for determinism)

Operational Notes
- Do not include external npm packages
- Redact sensitive fields from openclaw.json on backup
- Always produce a manifest.json with file sizes and hashes