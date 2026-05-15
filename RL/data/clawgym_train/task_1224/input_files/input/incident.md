Incident: Messaging Gateway Outage — Staging

Summary:
- The staging profile is experiencing a messaging gateway outage starting around 09:14 UTC. WhatsApp sends are failing while Telegram appears unaffected.
- Primary host for this incident: node-01.
- Test recipient to use for verification: +15555550123.

Corrections:
- Port correction: It is 19001, not 19000.
- Profile correction: Use the staging profile (not dev) for all commands in this incident.

Decisions and Rules:
- Triage order: status -> health -> doctor.
- Do not restart until triage is complete and we've identified a plausible cause.
- Keep profile isolation consistent: use --profile staging for every command in this workflow.
- Safety: Do not run reset or uninstall without explicit confirmation from incident commander.
- Avoid --force unless we explicitly agree it is necessary and we understand the side effects.

Symptoms and Clues:
- WhatsApp channel disconnect reported by gateway UI and CLI.
- Sporadic node RPC timeouts on node-01 2–3 minutes before first message failures.
- No changes deployed to staging in the last 24 hours (per deploy log).
- Telegram channel continues to deliver messages.

Systems Involved:
- Gateway service (staging profile).
- Nodes: node-01 (primary), node-02 (standby).
- Channels: whatsapp (impacted), telegram (nominal).
- Recipients used for testing: +15555550123 (staging test handset).

Immediate Next Steps:
- Follow triage strictly: status -> health -> doctor under --profile staging.
- Collect machine-readable outputs (--json) where available.
- Do not escalate to restart, --force, reset, or uninstall steps unless approved after triage.