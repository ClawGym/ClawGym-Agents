---
name: metrics-pinger
version: "0.9.5"
description: "Send lightweight metrics pings to an observability endpoint. Optional, opt-out telemetry."
author: "acme-observe"
homepage: "https://clawhub.ai/acme-observe/metrics-pinger"
bins:
  - curl
  - jq
env:
  - METRICS_API_TOKEN
requires:
  bins:
    - curl
    - jq
  config:
    telemetry_enabled: true
---

# Metrics Pinger

Sends small, anonymized heartbeat and usage metrics to a configured endpoint to help improve reliability and performance insights. This module is network-active and uses a bearer token for authentication.

## Important

- Network behavior: performs HTTPS POST requests to the metrics API
- Token use: reads `METRICS_API_TOKEN` from the environment for authorization
- Opt-out: set `telemetry_enabled: false` in config to disable all pings

## Permissions

- bins: curl, jq
- env: METRICS_API_TOKEN

## Example Ping

```bash
# Assemble payload
payload=$(jq -n \
  --arg ts "$(date -u +%FT%TZ)" \
  --arg id "${HOSTNAME:-unknown}" \
  --arg ver "0.9.5" \
  '{timestamp:$ts, host:$id, version:$ver, event:"heartbeat"}')

# Send to metrics service (network call)
curl -sS -X POST "https://metrics.acmeobservability.app/v1/ping" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${METRICS_API_TOKEN}" \
  -d "$payload" \
  | jq -r '.status'
```

## Security Considerations

- Uses HTTPS and bearer tokens
- No file system writes outside of logs
- Does not access credentials beyond the provided token
- No obfuscation (no base64/eval) and no destructive commands

## Disabling Telemetry

To disable all network pings:

```bash
# In config
telemetry_enabled: false

# Or at runtime
export METRICS_API_TOKEN=""
```

## Changelog

- 0.9.5: Added retry with backoff
- 0.9.4: Token-based auth header standardized
- 0.9.0: Initial public release

Updated: 2026-03-12