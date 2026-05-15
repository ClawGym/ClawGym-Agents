# system.md — Environment and Constraints

Updated: 2026-04-15

## Environment
- OS: Linux (containerized)
- Shell tools available: bash, grep, find, wc
- Network: Limited by default. Outbound HTTP allowed only for approved endpoints; no API credentials preconfigured.
- Filesystem: ./input mounted read-only; outputs must be written under ./output
- Context compaction: Sessions may compact after ~200 turns; long sessions are common.

## Workspace Structure (current)
- Present: AGENTS.md, SOUL.md, system.md
- Absent: QA.md, .learnings/* (not yet created), memory/working-buffer.md (not yet created)

## Operational Cadence
- Heartbeat: every 30 minutes (scheduler calls the orchestrator with minimal context)
- Daily sync: human reviews status each morning; expects concise, evidence-backed updates

## Known Issues and Incidents
- 2026-03-27: A scheduled monitor produced a plausible-looking report when its data source failed; no error surfaced. Root cause: missing fail-closed rule in isolated runs.
- Multiple handoffs lacked explicit artifact paths; orchestrator had to reverse-engineer results. No Acceptance Gate or Completion Contract.

## Aave Monitoring (planned)
- Goal: Add a scheduled sub-agent to report wallet Health Factor and liquidation risk across chains.
- Credentials: None stored. Use public endpoints (e.g., Aave subgraph) if accessible; otherwise fail-closed.
- Wallets to monitor: TBD by operator (unknown at this time)
- Deliverables: Expect machine-readable JSON and a short human summary per run; exact paths TBD by the orchestrator during setup.

## Constraints and Expectations
- Do NOT modify input files; produce new artifacts under ./output
- No sending emails or webhooks from this environment; plans should describe routing, not perform it
- Prefer deterministic commands and observable checks
- Mark unknowns explicitly as TBD; do not invent details to fill gaps