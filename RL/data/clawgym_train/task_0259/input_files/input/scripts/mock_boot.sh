#!/usr/bin/env bash
# Deterministic mock boot log generator for local verification
cat <<'LOG'
2026-03-14T10:00:00.000Z [gateway] STARTING
2026-03-14T10:00:01.120Z [gateway] UP in 1120 ms
2026-03-14T10:00:00.100Z [users] STARTING
2026-03-14T10:00:00.950Z [users] UP in 850 ms
2026-03-14T10:00:01.000Z [inventory] STARTING
2026-03-14T10:00:01.740Z [inventory] UP in 740 ms
2026-03-14T10:00:01.500Z [orders] STARTING
2026-03-14T10:00:03.600Z [orders] UP in 2100 ms
2026-03-14T10:00:02.000Z [payments] STARTING
2026-03-14T10:00:03.650Z [payments] UP in 1650 ms
2026-03-14T10:00:02.500Z [billing] STARTING
2026-03-14T10:00:03.400Z [billing] FAIL after 900 ms
LOG
