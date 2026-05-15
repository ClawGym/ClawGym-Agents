# Agent Memory

- Last session: 2026-03-10 12:30 UTC
- Context summary: Migrating agent state to a new machine for secure backup and restore.
- Key files tracked:
  - .openclaw/openclaw.json
  - clawd/MEMORY.md

Notes:
- Ensure encrypted export uses AES-256-GCM.
- Manifest should capture original workspace path for normalization on restore.