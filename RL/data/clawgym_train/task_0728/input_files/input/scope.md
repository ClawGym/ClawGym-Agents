Network Health Check — Scope and Guardrails

Purpose:
- Run a lightweight, non-intrusive health check on the local network and connectivity.

Required tests:
- Interfaces status: list interfaces, operational state, MAC, RX/TX totals.
- Listening TCP ports: list only (no scans).
- Bandwidth estimate: sample over ~5 seconds using OS counters.
- For each host in targets.json:
  - Latency test: ~5 ICMP pings (short timeout, handle ICMP restrictions).
  - Traceroute/tracepath: cap at ~15 hops, short per-hop timeout.
  - DNS lookup: resolve A/AAAA records.
  - WHOIS: only for domain-type hosts (contains a dot and at least one alpha character).
- Download speed test: attempt a small download (≈1 MB), short timeout.

Operational guardrails:
- Total runtime target: ≤ ~30 seconds.
- Use brief timeouts; do not block on slow commands. If a command/tool is missing or times out, mark as attempted/failed and continue.
- Do not modify system settings or require elevated privileges.
- No port scanning or intrusive probing.
- Prefer built-in tools (ss/netstat, ping, traceroute/tracepath, whois) if available.

Outputs (write only to output/ paths):
- output/network_report.md with sections in this exact order:
  1. Interfaces
  2. Listening Ports
  3. Bandwidth
  4. Latency Tests
  5. Traceroutes
  6. DNS Results
  7. WHOIS Summaries
  8. Speed Test
  9. Recommendations
- output/metrics.json with fields:
  - tested_hosts (array), timestamp (ISO), interfaces (array), latency (object), dns (object),
    traceroute (object), whois (object), bandwidth (object), speed_test (object).
- output/commands_run.jsonl: one line per action with fields cmd, target (if any), status ("attempted" | "success" | "failed").

Notes:
- Record one entry each for: interfaces/status, ports/listening, bandwidth, speed test.
- For each host: one entry each for latency, traceroute, dns; whois only for domain hosts.
- Keep report concise, note failures/timeouts plainly, and include short recommendations based on observed results.