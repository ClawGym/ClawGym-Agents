Overview
- This run covers three builds for player p-77-01 using the same signing key ops-key-77.
- Requested builds match the following Struct types and ambits:
  - Command Ship Alpha (type_id 1) — ambit space, slot 0
  - Ore Refinery Gamma (type_id 15) — ambit land, slot 1
  - PDC Sentinel (type_id 19) — ambit land, slot 2
- All ambits must be lowercase strings: "space", "air", "land", or "water".
- Use the literal CLI argument separator " -- " before positional arguments to prevent IDs with dashes from being parsed as flags.

Sequencing and priorities
- Single signing key policy: one key, one compute at a time. Do not run concurrent compute jobs with ops-key-77.
- Compute sequencing priority:
  1) st-1100-ax (Command Ship Alpha, type_id 1)
  2) st-4521-rf (Ore Refinery Gamma, type_id 15)
  3) st-9902-pdc (PDC Sentinel, type_id 19)
- Reasoning:
  - Command Ship should go online first to avoid “Command Ship required” blockers for planet-side operations.
  - Refinery before PDC to bring processing capacity online; PDC can follow once infrastructure is active.

Charge and timing
- Charge cost for build completion (compute) is 8 per struct.
- Charge accrues at ~1 per block (~6 seconds). Plan for at least 8 blocks (~48 seconds) between build actions if charge is low.
- Expected wait to D=3 (approximate, acceptable variance ±5 minutes):
  - type_id 1 (Command Ship): ~17 minutes
  - type_id 15 (Ore Refinery): ~57 minutes
  - type_id 19 (PDC): ~222 minutes (~3.7 hours)
- Initiate builds early, then run compute at D=3 to complete instantly with minimal resource use (-D 3).

Operational prerequisites and limits
- Ensure fleet is on-station at the target planet for land builds before running compute; Command Ship Alpha will be brought online first to support subsequent operations.
- One PDC per player limit applies. This is the only PDC planned for player p-77-01 in this run.
- Power capacity checks should be performed if additional structures are already online to avoid “power overload”.

Risks and reminders
- Do not run concurrent compute jobs with the same key (ops-key-77) to avoid transaction sequence conflicts.
- Generator infusion is irreversible; not part of this run.
- Always keep ambit values lowercase and include the literal " -- " separator before positional arguments in all tx commands.