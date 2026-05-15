# Changelog

All notable changes to this project are documented in this file.

## [2.4.0] - 2026-04-18
### Added
- Smart cache layer for dashboard queries (behind `features.enableSmartCache`)
- Telemetry batching and flush interval controls
- Admin setting to pick default UI timezone

### Fixed
- Addressed race condition in notification bell badge count
- Resolved intermittent auth token refresh edge-case after 24h idle

### Changed
- Increased default telemetry batch size to 200 for staging
- Elevated API retry backoff upper bound to reduce spike storms

## [2.3.1] - 2026-03-29
### Fixed
- Mitigated UI freeze on large project board drag events
- Corrected label color contrast in dark theme

## [2.3.0] - 2026-03-18
### Added
- New “Projects Overview” widget on home dashboard
- Export to CSV for activity logs

[Unreleased]: https://example.com/horizondesk/compare/2.4.0...HEAD
[2.4.0]: https://example.com/horizondesk/releases/2.4.0
[2.3.1]: https://example.com/horizondesk/releases/2.3.1
[2.3.0]: https://example.com/horizondesk/releases/2.3.0