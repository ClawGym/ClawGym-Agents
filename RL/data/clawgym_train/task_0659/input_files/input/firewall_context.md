# Firewall Context and Change Scope

Owner: NetSec + SRE
Change ID: FW-2026-0419-OPS
Maintenance Window: Sat 02:00–04:00 UTC (staging first, then production one week later)
Environments in Scope: staging (stg-*), production (prd-*)

## Environment Overview

- Linux Distros
  - Ubuntu 22.04 LTS (kernels 5.15+), iptables-nft by default
  - Ubuntu 20.04 LTS (kernels 5.4), mixed iptables-legacy and iptables-nft
  - RHEL 8.x / Rocky 8.x, iptables-legacy (iptables-services enabled on some hosts)
- Roles and Subnets
  - Web tier (nginx): 172.16.10.0/24
  - App tier (api-workers): 172.16.20.0/24
  - DB tier (PostgreSQL): 172.16.30.0/24
  - Cache tier (Redis): 172.16.40.0/24
  - Bastion/jump: 10.30.5.10
  - Management plane (SSH, Ansible, backups, Prometheus): 10.20.0.0/16 and 10.40.0.0/16
  - Internal DNS: 10.50.0.53, 10.50.0.54
- Load balancers terminate TLS and forward to web tier via 80/443 within VPC
- High availability: active/active web/app behind LBs; DB uses primary/replica

## Current Posture (Baseline)

- Many hosts inherit allow-all inbound on local iptables with reliance on VPC security groups.
- iptables default policies are ACCEPT in several places; logging is inconsistent.
- IPv6 is enabled on a subset of Ubuntu 22.04 hosts; ip6tables not consistently configured.

## Desired Posture (Target)

- Enforce host-based controls in addition to network security groups.
- Principle of least privilege: only allow traffic that is explicitly required.
- Consistent logging and rate-limited drop logs.
- Standardized rules across tiers with role-specific exceptions.
- Prepare staging, rollback, and verification procedures.

## Change Scope Summary

- Switch host firewall posture to stateful default-deny on INPUT for all tiers.
- Standard conntrack rule placement (ESTABLISHED,RELATED early accept).
- Role-based allows (SSH restricted to management, app-to-DB, monitoring).
- Rate-limited logging of drops with clear prefixes.
- Outbound policy remains default-allow for now, with future tightening for egress.
- Align IPv6 behavior with IPv4 (or explicitly drop if service is IPv4-only).
- Prepare migration steps for iptables-nft vs iptables-legacy hosts.

## Ports and Access Matrix (Highlights)

- SSH (22/tcp): Only from 10.20.0.0/16 (Mgmt) and 10.30.5.10 (Bastion)
- HTTP/HTTPS (80,443/tcp): Web tier inbound from LBs/VPC; intra-cluster health checks allowed
- PostgreSQL (5432/tcp): DB tier accepts only from App tier (172.16.20.0/24)
- Redis (6379/tcp): Cache tier accepts only from App tier (172.16.20.0/24)
- Prometheus Node Exporter (9100/tcp), Blackbox (9115/tcp): Only from 10.40.0.0/16
- NTP (123/udp): Outbound to approved time sources
- DNS (53/udp,tcp): Outbound to 10.50.0.53 and 10.50.0.54
- ICMP: Permit limited echo-request/reply for diagnostics; rate-limit as needed

## Logging

- Use rsyslog kern.* with identifiable prefixes.
- Drop log prefix: "FW-DROP "
- Rate limit logging to prevent flood:
  - -m limit --limit 5/min --limit-burst 10 (tune per role)

## Performance Considerations

- Place ESTABLISHED,RELATED early to minimize rule traversal.
- Use multiport where reasonable for grouped services.
- Keep logging rate-limited and specific to drops; avoid LOG on hot paths.
- Use comments (-m comment --comment "<rule-id>") for maintainability.
- Ensure conntrack table sizing is adequate for web tier bursts (monitor nf_conntrack).

## IPv6

- Mirror IPv4 policy in ip6tables where IPv6 is enabled.
- If a host/service is IPv4-only, set ip6tables default DROP and allow only necessary loopback.
- Ensure no IPv6 bypass if IPv6 stack is present.

## NAT Considerations

- No new NAT on app/web/db hosts; NAT only on egress/NAT gateways.
- Bastion/jump and NAT gateways are out of scope for functional changes except standard INPUT policy enforcement.

## Staging and Rollback

- Staging first: apply to stg-* hosts, monitor for a full business day.
- Rollback plan:
  - Save current rules before change: iptables-save > /var/backups/iptables-<date>.rules
  - Restore via iptables-restore if needed.
  - Maintain console access; keep an emergency revert script ready.
  - For Ubuntu, use netfilter-persistent save/restore; for RHEL, service iptables save/restore.
- Staging validation criteria:
  - All SLOs normal (error rates, latency).
  - No unexpected drop spikes in logs.
  - Prometheus scrape success.
  - SSH reachable from management only.

## Automation

- Managed via Ansible:
  - Template rules per role; idempotent application.
  - Verify nft vs legacy backend with "iptables -V" and "update-alternatives --display iptables" or distro-specific checks.
  - Use iptables-restore atomically when possible.
- Persist rules:
  - Ubuntu: netfilter-persistent (iptables-persistent)
  - RHEL: iptables-services

---

# Requested Firewall Change (Detailed)

- Default Policies
  - INPUT: DROP
  - FORWARD: DROP (non-router hosts)
  - OUTPUT: ACCEPT (phase 1; tighten later)
- Baseline Accepts (top of chains)
  - -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  - -A INPUT -i lo -j ACCEPT
- SSH Access
  - -A INPUT -p tcp -s 10.20.0.0/16 --dport 22 -m conntrack --ctstate NEW -j ACCEPT
  - -A INPUT -p tcp -s 10.30.5.10/32 --dport 22 -m conntrack --ctstate NEW -j ACCEPT
- Web Tier (on web nodes only)
  - -A INPUT -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -j ACCEPT
- DB Tier (on db nodes only)
  - -A INPUT -p tcp -s 172.16.20.0/24 --dport 5432 -m conntrack --ctstate NEW -j ACCEPT
- Cache Tier (on cache nodes only)
  - -A INPUT -p tcp -s 172.16.20.0/24 --dport 6379 -m conntrack --ctstate NEW -j ACCEPT
- Monitoring (all nodes exposing exporters)
  - -A INPUT -p tcp -s 10.40.0.0/16 -m multiport --dports 9100,9115 -m conntrack --ctstate NEW -j ACCEPT
- ICMP (rate-limited)
  - -A INPUT -p icmp -m icmp --icmp-type echo-request -m limit --limit 5/second --limit-burst 20 -j ACCEPT
- Logging and Final Drop
  - -A INPUT -m limit --limit 5/min --limit-burst 10 -j LOG --log-prefix "FW-DROP " --log-level 4
  - -A INPUT -j DROP

Notes:
- Apply equivalent ip6tables rules where IPv6 is used (or default DROP with loopback only if v6 not needed).
- Use -m comment to tag rules with Change ID for audits.

---

# Risks and Mitigations

- Accidental lockout (SSH): Mitigate by adding SSH allows first, validating connectivity, using screen with fallback revert script.
- Service disruption: Test in staging; verify via health checks and Prometheus.
- Logging flood: Use rate-limits; monitor rsyslog throughput.
- nft vs legacy mismatch: Detect and branch tasks; validate ruleset after application.

---

# Validation Plan

- Pre-change:
  - Confirm console access and working revert procedure.
  - Capture current iptables-save and ip6tables-save snapshots.
  - Confirm monitoring dashboards for baseline.
- Post-change (staging and production):
  - SSH from management subnets succeeds; from non-management source fails.
  - Web/app endpoints healthy behind LB.
  - App-to-DB and App-to-Cache connections succeed; others fail.
  - Prometheus scrape successful.
  - Examine /var/log/kern.log or journalctl -k for "FW-DROP" entries; confirm expected drops only.

---

# Communication

- Notify netops and app owners prior to change.
- Include rollback instructions and contact channel.
- Request netops to run independent baseline and acknowledge.

---

# Appendix

- Distro Persistence:
  - Ubuntu: apt install iptables-persistent; systemctl enable netfilter-persistent; netfilter-persistent save
  - RHEL: yum install iptables-services; systemctl enable iptables; service iptables save
- Useful Commands:
  - iptables -S; iptables -L -n -v
  - iptables-save; iptables-restore
  - conntrack -L (if installed)

This change adheres to the principle of least privilege, enforces consistent logging, includes a robust staging approach, and provides a tested rollback path.