Environment:
- Platform: Synology DS920+ (DSM 7.2)
- Storage: 4 x 8TB HDD (SHR-1), ~14TB currently used (70% capacity)
- Cache: 2 x NVMe for read cache (Docker configs on NVMe volume)
- Network: 1 Gbps LAN, router with dynamic public IP (no static IP)
- Users/Clients: 6 users total — 4 Windows 11 laptops (SMB), 1 macOS Ventura (SMB), 1 Ubuntu workstation (prefers NFS for a build cache)
- Services/Apps: Jellyfin, Paperless-ngx, Home Assistant, Nginx Proxy Manager (local only), Synology Drive
- Current Remote Access: None (no ports forwarded). Considering Tailscale.
- Backup Status: Ad-hoc external USB backup monthly (manual). No cloud backup yet.
- Power: Small UPS on router only; NAS not on UPS (planning to buy one).

Goals:
- Implement a proper 3-2-1 backup strategy with verifiable restores.
- Zero-port-exposure remote access for two remote contractors and family media access.
- Clear protocol guidance: SMB for Windows/Mac shares; NFS for the Ubuntu build cache only.
- Harden security (disable default admin, 2FA, firewall rules, automatic updates within a maintenance window).
- Media streaming should prioritize direct play; avoid heavy transcoding when possible.

Constraints / Assumptions:
- Upstream bandwidth ~20 Mbps; cloud backup windows must be scheduled overnight.
- Willing to use Backblaze B2 for cloud backups and rotate a USB drive off-site monthly.
- Recovery objectives: RPO <= 24 hours for documents/configs, RTO <= 8 hours for critical services (Home Assistant, Paperless-ngx).
- Desire to keep Jellyfin reachable for family without exposing public ports (VPN preferred).

Threat Model:
- Primary risk: Ransomware via compromised client devices.
- Secondary risks: Drive failure, power loss, accidental deletion, remote access abuse if misconfigured.

Questions for the plan:
- Exact Tailscale/WireGuard setup recommendations?
- Firewall rules per service?
- Snapshot and backup retention policies for documents vs media?
- How to test restores quarterly without disrupting production?