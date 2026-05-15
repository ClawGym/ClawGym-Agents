Background
We are investigating suspicious login activity targeting corporate SSO and developer resources. Several attempts originated from unfamiliar networks, off-hours locales, and potential anonymization services. Use the targets list to enrich with network intelligence so we can decide on containment (temporary blocks, step-up auth) and escalation (contacting providers).

Priorities
- Resolve hostnames to IPs; continue even if some fail.
- For each unique target, collect: geolocation (country, region/city), ISP, ASN, PTR (reverse DNS), and RDAP/WHOIS ownership (network name, CIDR, abuse contact).
- Identify likely data center/cloud vs residential/dynamic sources.
- Note Tor/VPN indicators and any reputation hints available from free sources.
- Keep outputs machine-readable and ordered to support quick ingestion.

Caveats
- Geolocation may reflect hosting or CDN edges rather than end-user location.
- PTR records can be absent or generic; treat as a weak signal.
- RDAP ownership can differ from the actual service operator (e.g., cloud tenant vs provider).
- Dynamic IPs reassign frequently; expect potential false positives and time variance.
- IPv6 PTR may not be available; handle gracefully.

Action guidance
- Prioritize temporary blocks or stricter rate limits on clear data center or Tor sources.
- Use abuse contacts from RDAP for coordinated takedown/complaint when warranted.
- Monitor for repeated attempts from the same ASN/CIDR and consider CIDR-level controls.
- Cross-check with authentication telemetry (user agents, MFA prompts, behavioral anomalies) before permanent blocks.