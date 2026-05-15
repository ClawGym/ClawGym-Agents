# AGENTS

## Workflow Notes
- Manual commands:
  - npx compound-engineering review
  - npx compound-engineering snapshot
  - npx compound-engineering setup-cron
- Nightly review: intended at 22:30 local via clawdbot (not fully configured)
- Hourly snapshots: currently manual; no cron or heartbeat automation in place
- Commit messages: preferred pattern is "compound: daily review YYYY-MM-DD", but recent commits used "misc:" and "chore:" inconsistently

## Known Issues
- Cron jobs may fail due to PATH not set for non-interactive shells
- Risk of duplicating bullets if dedupe is not applied before writing
- Memory file path must be exactly memory/YYYY-MM-DD.md to avoid misfiled entries

## Next Planned Updates
- Finalize hourly snapshot automation (top of the hour) using absolute binary path
- Enforce commit message standard for all memory-related commits