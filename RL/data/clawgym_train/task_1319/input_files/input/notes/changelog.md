# Changelog

All notable changes to NebulaDrive are documented here.

## v1.2.0 (2025-02-28)
- Increased default chunk size from 8 MiB to 16 MiB for large file uploads.
- Improved conflict resolver to handle rename + edit races.
- Added admin policy to restrict external sharing by domain.
- Optimized thumbnail generation pipeline for HEIC images.

## v1.1.3 (2025-01-15)
- Fixed intermittent 429 responses on metadata listing under heavy load.
- Hardened JWT validation for WebSocket reconnects.

## v1.1.0 (2024-12-10)
- Introduced Batch Sync scheduling controls (5/10/15-minute windows).
- Added audit log export to Splunk and Datadog.

## v1.0.0 (2024-10-05)
- General availability release.