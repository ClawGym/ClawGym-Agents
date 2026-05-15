These notes guide how Engineering should use Moodring in our environment.

- Environment: Ubuntu LTS, bash shells by default. No external network calls required.
- Canonical source: Use the official Moodring command outputs (intro, quickstart, patterns, debugging, performance, security) as-is. Do not rewrite reference content.
- Versioning: Track the skill at the 2.0.x line. If command output and metadata versions differ, prefer the most recent reference text in the tool output.
- Operational norms:
  - Keep configurations in version control and document deviations from defaults.
  - Use staging to validate any change before production.
  - Always back up prior to migrations or major updates.
- Ownership: Platform Engineering maintains the reference pack; submit improvements via PRs to docs.
- Support path: Start with the Debugging section, gather logs, and escalate with a minimal repro when needed.