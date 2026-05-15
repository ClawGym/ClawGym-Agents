# Security Policy for Trend Evaluation and Planning

This policy governs how we evaluate third-party repositories for potential integration, focusing on safety, compliance, and operational hygiene.

## Prohibited Actions (Default)
- Do not clone or execute any external code during evaluation.
- Do not run shell commands from third-party sources.
- Do not send secrets, tokens, or proprietary data to external APIs without explicit approval.

## Allowed Actions (With Guardrails)
- Read-only artifact review: repository metadata, documentation, examples, and published API references.
- Local planning and design proposals (no code execution).
- Pre-install security scanning checklist preparation.

## Approval Gates
- Prior to any installation or code touching, complete the pre-install security scan checklist:
  - Exec: identify any command execution patterns.
  - Network: enumerate outbound calls and endpoints.
  - Filesystem: locate write/delete operations and data paths.
  - Sensitive: detect env var usage, credential paths, and token handling.
  - Domains: list domains; check against threat intel (local blacklist; optionally URLhaus, VirusTotal, etc., with keys).
- Licensing review: allow MIT / Apache-2.0 / BSD; avoid GPL/AGPL/LGPL for core dependencies.
- Data handling review: ensure prompts/telemetry do not include customer data unless anonymized and approved.

## Read-Only Fast Path
- For strictly read-only evaluations (metadata parsing, doc reading, config inspection), a fast path may be used:
  - Requires explicit confirmation/approval by the reviewer.
  - No network calls beyond documentation pages and official registries.
  - No filesystem writes outside temporary logs.

## Temporary Tooling Acquisition (On-Demand)
- Installation requires reviewer approval and a documented purpose.
- Generate an execution plan describing side effects (read-only vs write, network endpoints, credentials).
- Default behavior: uninstall/cleanup after evaluation.
- Switching/fallback: if a candidate tool fails install or violates guardrails, abort and pick the next approved candidate.

## Domain and API Use
- Maintain a local blacklist; check discovered domains prior to any external calls.
- If using threat intel APIs, use dedicated API keys and respect rate limits; never include customer data in queries.
- Prefer internal collectors for observability exports; avoid direct vendor endpoints unless vetted.

## Logging and Self-Improvement
- Log learnings, errors, and feature requests in .learnings/ using standardized format and IDs.
- Promote broadly applicable rules to AGENTS.md (operational guidance).
- Review logs before major tasks and weekly during active development.