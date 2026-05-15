# Crypto Module (Local Dev)

This repo contains a minimal crypto module used for local development and validation flows. It includes a simulated AES-256-GCM implementation and a legacy RC4 helper for compatibility testing.

Files:
- config/security.json — local security policy (FIPS mode, allowlist/denylist).
- crypto_lib/algos.py — crypto functions (includes AES-256-GCM and RC4).
- tests/run_validation.py — validation script to check a basic encrypt/decrypt round trip using the first allowed algorithm.

Do not use this code for production cryptography. It exists solely to support tooling and audits.
