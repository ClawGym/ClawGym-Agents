# Incident Report: Controller Disconnects on 2025-02-10

## Summary
Top disconnect reason: {{TOP_REASON}} ({{TOP_REASON_COUNT}} events).
Most affected device: {{TOP_DEVICE}} ({{TOP_DEVICE_COUNT}} disconnects).

## Evidence
- Ranked reasons CSV: outputs/analysis/disconnect_rank.csv
- Frequent offenders CSV: outputs/analysis/frequent_offenders.csv

## Configuration Snapshot
- heartbeatIntervalMs: {{CONFIG_HEARTBEAT_MS}}
- disconnectAfterMs: {{CONFIG_DISCONNECT_MS}}
- Timeout implementation function: {{TIMEOUT_FUNCTION_NAME}}

## Notes
This is a quick analysis for lab triage; follow up with a full postmortem if necessary.