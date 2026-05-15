# Changelog

All notable changes to this project will be documented in this file.

## [1.4.0] - 2026-04-15
### Added
- Observability docs and basic dashboards
- Health endpoints with dependency checks
- SBOM generation in CI for npm and pip

### Changed
- Upgraded core libraries (minor versions)

### Fixed
- Flaky e2e test for checkout flow

## [1.3.1] - 2026-03-28
### Fixed
- API 500 on orders endpoint when item count > 50

## [1.3.0] - 2026-03-20
### Added
- Payment flow improvements with idempotency keys