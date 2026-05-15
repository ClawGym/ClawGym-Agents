# AGENTS — Instructions and Workflows

Workflows
1) Daily Backup
   - Trigger: 02:00
   - Action: Create timestamped backup with SHA-256 manifest
   - Post: Log summary and disk usage

2) Pre-Change Checkpoint
   - Trigger: Manual before major edits
   - Action: Create named backup
   - Post: Print restore command hint

3) Validation Sweep
   - Trigger: Weekly (Sunday 03:00)
   - Action: Verify manifests, existence, and hashes
   - Post: Report warnings/errors

Operational Rules
- Never overwrite without a pre-restore backup
- Always support dry-run previews
- Sanitize openclaw.json when backing up