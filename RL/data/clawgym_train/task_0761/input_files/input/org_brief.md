# Org Brief — Community Literacy Alliance (CLA)

Overview
- CLA is a small 501(c)(3) focused on adult and youth literacy programs in our county.
- Staff: ~12 employees + ~30 rotating volunteers. IT is part-time (1 person) with contractor support as needed.
- Infrastructure: Mixed Windows laptops (mostly Windows 10/11), a Synology NAS hosting SMB shares, and a few Macs for creative work. Some staff occasionally work from personal devices (BYOD with policies).
- Data sensitivity: Contains donor PII, client intake forms, grant applications, and program rosters. We must never scan or read file contents — metadata only.

NAS Inventory Initiative Goals
- Build a metadata-only map of what’s on the NAS (paths, sizes, timestamps, extensions) to:
  - Identify duplicates, stale content, and storage hotspots.
  - Prepare for policy clean-up and longer-term retention standards.
  - Improve staff support (find files faster, reduce “lost in folders” time).
  - Demonstrate stewardship for audits and grant compliance reviews.

Operational & Safety Constraints
- Read-only scanning only. No file writes, renames, deletions, permissions changes, or attribute edits.
- Offline by default. The NAS segment has no outbound internet; tools must function without network access.
- Cross-platform: Run from a Windows laptop if possible; Linux/macOS compatibility is helpful for contractor assist.
- No software installs on the NAS. Scanner runs from an admin/jump laptop connected to the NAS via SMB.
- No agent should write any output files back to the NAS. Save outputs to the local workstation or an encrypted USB.
- Minimize disruption: Schedule after-hours (6pm–7am) to avoid share contention.
- Privacy: Do not open files. Do not extract content. Only metadata (name, path, size, timestamps, extension). Prefer relative paths (relative to the provided root) in any generated JSON.
- Performance & Footprint: The NAS has large directories (some with 50k+ items). Scanner must handle permission errors gracefully and skip unreadable locations without crashing.

Contextual Realities
- Shares are organized by department: Programs, Development (fundraising), Operations, and Shared.
- Legacy folders from pre-2021 migration still exist, sometimes deeply nested (up to 15+ levels).
- Symlinks/shortcuts: There are a few Windows .lnk shortcuts and some Synology symlinked folders. Default behavior should not follow symlinks.
- Large media: Program photos and video clips consume space; we need to quantify by extension without processing contents.
- Timeline: We want a first-pass inventory within 2–3 weeks, with simple reporting for an internal readout at the next board meeting.

Success Indicators
- A JSON file inventory of metadata suitable for future SQLite storage.
- An offline HTML report that non-technical staff can use locally to view summary counts and browse by folder.
- A pragmatic plan that fits our staffing, budget (near-zero), and privacy obligations.

Notes for Messaging (Internal Rollout)
- We want buy-in without fear. Emphasize: privacy-first, no content scanning, and benefits to everyday work (finding files faster).
- Focus on stewardship and readiness — helps with grants and audits.
- Avoid “compliance policing” tone. Show immediate staff wins (faster support, less clutter).