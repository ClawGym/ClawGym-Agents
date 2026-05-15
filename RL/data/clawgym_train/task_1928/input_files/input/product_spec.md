# ORION-77 FieldOps Rebuild — Product Specification

Codename: ORION-77
Product: FieldOps mobile app for field technicians and shift supervisors
Platforms: iOS and Android (single codebase with platform-appropriate UX)

## Goals
- High-reliability offline operation for remote/rural field work
- Faster task execution: reduce taps and screen transitions for top flows
- Reduce battery usage (especially around location and background sync)
- Improve navigation clarity and deep link routing for dispatch workflows
- Bring feature parity across iOS and Android with platform conventions respected
- Enable supervisors to coordinate work, approve timesheets, and locate teams

## Primary Roles
1) Field Technician
- Needs: quick access to assigned work orders, barcode scanning, photo capture, offline updates with automatic sync, simple maps for routing
- Context: gloves, bright sunlight, intermittent connectivity (offline/2G/3G)

2) Shift Supervisor
- Needs: schedule board overview, technician locator map with low battery impact, work order reassignment, approvals (timesheets/WO), notifications triage
- Context: office and field mixed, reliable wifi/LTE, occasionally low-signal yards

## Primary Screens and Route IDs
- Login (route: login)
- Dashboard (route: dashboard)
- Work Orders List (route: work_orders_list)
- Work Order Detail (route: work_order_detail)
  - Subflows: Start, Pause, Complete, Labor/Parts, Photos, Notes
- Barcode Scanner (route: scanner)
- Map & Route (route: map_route)
- Asset Detail (route: asset_detail)
- Offline Outbox (queued actions) (route: outbox)
- Reports / Shift Summary (route: reports)
- Notifications Inbox (route: notifications_inbox)
- Settings (route: settings)
- Supervisor Schedule Board (route: supervisor_schedule)
- Technician Locator (route: supervisor_locator)
- Approvals (timesheets, work order approvals) (route: approvals)

## Key Flows
- Accept Work Order: deep link from dispatch -> open Work Order Detail -> Start -> execute tasks -> Complete with signature/photo evidence
- Capture Evidence: add photos and barcodes to work order steps (camera-first flow)
- Offline Execution: capture all actions offline (status, notes, media) -> queued in Outbox -> retry with exponential backoff on reconnect
- Supervisor Dispatch: open Schedule Board -> assign/reassign work orders -> technician notified (push) -> link opens WO in-app
- Technician Locator: low-frequency background updates; on-demand higher-accuracy ping from supervisors with user consent

## Deep Link Requirements
- Open specific work order by ID: orion://work-order/{id}
- Optional action in query: orion://work-order/{id}?action=start|resume|review
- Open asset by assetId: orion://asset/{assetId}
- Open daily report by date: orion://report/{YYYY-MM-DD}
- Approvals tab: orion://approvals/{tab} (timesheets|work-orders)
- Web fallback (when app not installed): https://fieldops.example.com/... matching patterns

## Performance Targets
- Cold start: ≤ 2 seconds on mid-tier devices (A13/Mid Snapdragon class)
- Scroll and screen transitions: 60fps target, avoid jank
- Startup network: defer non-critical calls >3 seconds post first render
- Background sync: staggered, respect iOS/Android background task limits
- Memory: prioritized caches, release on low-memory signals
- Battery: reduce location polling; batch network requests; avoid wake-locks

## Security & Data
- Authentication: OAuth2 with refresh tokens
- Tokens stored in Keychain (iOS) / Keystore (Android)
- At-rest encryption for sensitive local data; do not store PII in logs
- Media: store locally until upload succeeds; include checksum on upload

## Accessibility & Ergonomics
- Large touch targets (≥44pt)
- Dynamic type for text-heavy screens
- High contrast; supports dark mode
- Alternatives for color-only indicators; glove-friendly controls

## Non-Functional
- Crash-free sessions ≥ 99.5%
- Offline-first: app usable for a full shift without connectivity
- Privacy: permission requests only when needed and with rationale

## Analytics & Telemetry (non-PII)
- Sync success/failure rates
- Crash and ANR metrics
- Battery impact sampling per feature (location heavy areas)

## Success Metrics
- Reduce work order completion time by 20%
- Reduce battery drain by 30% during locator usage
- ≥ 95% of evidence uploads succeed within 10 minutes of connectivity