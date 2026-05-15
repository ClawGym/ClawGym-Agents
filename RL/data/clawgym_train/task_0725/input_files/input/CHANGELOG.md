# Changelog

All notable changes to this project are documented here.

## v1.4.3 — 2026-04-20 (pending quality gate)
- Feature: Introduce `--retry` with exponential backoff and jitter for network subcommands (`install`, `fetch`, `update`).
- Defaults: 3 attempts, base delay 250ms, capped at 5s with full jitter.
- Docs: README updated with examples and configuration.
- Rationale: Responds to user feedback (#231, ops note) and telemetry showing 12% first-attempt network error rate.
- Status: Not released yet — awaiting pre-release quality gate approval.

## v1.4.2 — 2026-04-19
- Fix: Stabilize progress indicator under heavy I/O (#228).
- UX: Colorized logs with severity-based palettes.
- Known issue: Transient network failures under poor connections (to be addressed in v1.4.3).

## v1.4.1 — 2026-04-18
- Perf: Improve template cache warm-up (~15% faster on cold start).
- Chore: Dependency updates and internal refactors.

## v1.4.0 — 2026-04-17
- Major: Parallel fetch pipeline with integrity verification.
- DX: `acorn doctor` adds environment diff output.
- Docs: Expanded troubleshooting section.