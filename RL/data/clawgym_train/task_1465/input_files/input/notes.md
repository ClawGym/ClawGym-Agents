data-ingest-pro — internal skill (packaged doc + starter resources) to standardize inbound data pipelines for CSV / JSON / XML. Goal: make ingest→validate→transform→export predictable, documented, and easy to adopt across teams.

Who uses this:
- Data Engineering (owner/maintainer)
- Analytics/BI (consume outputs, specify schema)
- RevOps/Marketing Ops (upload vendor exports, CRM dumps)
- QA / Compliance (validation, PII handling)
When to use:
- New vendor feed onboarding (CSV/JSON/XML) with recurring cadence
- Partner SFTP drops or HTTPS endpoints, daily batch imports, webhook payloads
- Replacing ad-hoc scripts with a repeatable, documented path
- Need lightweight, documented ingest with validations and mapping templates
Not meant for: full-fledged ETL platform replacement; this is a structured skill template + stub resources and guidance for typical flat/semi-structured payloads

Supported formats (MVP):
- CSV: RFC 4180-ish, header row expected; delimiter usually comma, may support tab/semicolon via config; quoted fields; optional gzip (.gz) and zip (.zip)
- JSON: standard JSON array OR NDJSON (one JSON object per line); UTF-8 by default; optional gzip
- XML: basic namespace-aware parsing; path-based extraction; optional gzip
Assume small-to-mid batch sizes for onboarding docs; streaming is optional (note below)

Sources (common):
- Local file (manual upload), S3/GCS bucket, HTTPS download, SFTP, (nice-to-have: Kafka topic for streaming JSON later)
Sinks (common):
- Postgres (OLTP tables), BigQuery/Snowflake (analytics), Parquet in lake, sanitized CSV/JSON outputs, webhook/API callback

Typical flow (keep this phrasing in docs):
- ingest → validate → transform → export
  - ingest: fetch file(s) from source, basic sniffing (format, encoding)
  - validate: schema + type checks, required fields, enums, row-level rules, custom validators (Python stubs)
  - transform: mapping templates (rename fields, normalize, derive), enrichment via reference lookups, PII masking/tokenization where required
  - export: write to target system(s) with idempotency (dedupe by natural keys), basic load reporting

Positioning:
- “Pro” = clarity + repeatability + governance (schema + naming + logs), not “enterprise ETL”
- Faster time-to-onboard vendor feeds; standardized validators; consistent naming for tables/files/jobs; baseline observability
- Works across CSV/JSON/XML — single skill your teams recognize
- Interoperates with async orchestration (tool-agnostic guidance in references)

Validation details:
- CSV: header presence, delimiter detection, required columns, type casting, null policy, date/time parsing, value ranges
- JSON: structure (array vs NDJSON), required keys, nested extraction paths, type checks, enum membership
- XML: XPath or element path configs, namespace handling, required nodes, type casting
- Report invalid rows separately; config option to “fail fast” or “quarantine bad rows”
- Row count, pass/fail counts, sample errors

Transformation details:
- Field mappings (assets/templates hold examples), normalization (case, trim, whitespace), date formats (ISO 8601), currency normalization, categorical normalization (e.g., country codes)
- Reference lookups (e.g., product id map), add metadata fields (source, ingest_ts), hashing for PII tokenization
- Keep mapping templates human-readable and versioned (document in assets/templates/README.md)

Export details:
- Targets configurable; default examples: parquet/CSV artifact and Postgres table
- Idempotency: natural key composite or hash; upsert or insert-once; configurable conflicts policy
- Basic load manifest (counts, hashes) + summary log

Async orchestration (generic, keep guidance tool-agnostic in references):
- priority for urgent feeds (e.g., finance first), retries with backoff, dependency chains (validate waits for ingest), concurrency limits (avoid overloading DB), per-task timeout defaults, structured logging per task
- sensible defaults: max_retries=3, base_retry_delay=5s, timeout=30s per task, concurrency=2 (document as assumptions)

Naming conventions (proposed):
- Datasets/tables: snake_case (e.g., partner_orders), staging prefix “stg_” if temporary
- Files: kebab-case + ISO date/time, e.g., partner-orders-2026-04-17.csv
- Jobs: data-ingest-pro::<source>::<dataset>::<stage> (e.g., data-ingest-pro::s3::orders::validate)
- Columns: snake_case; consistent units; ISO 8601 for timestamps

Capabilities to highlight (capabilities-based structure fits best):
1) Source Connectors & Intake (local/S3/GCS/HTTPS/SFTP; basic format sniffing, compression support)
2) Validation Engine & Schema Registry (CSV/JSON/XML validators, rule sets, quarantine strategy)
3) Transformation & Mapping Templates (field rename/derive/normalize, enrichment, PII handling)
4) Exporters & Loaders (DB/DW/lake + manifests, idempotency, conflict policy)
5) Orchestration & Reliability (priority, retry/backoff, dependencies, concurrency, timeout, logging)
6) Observability & Governance (job logs, metrics, lineage breadcrumbs, naming conventions)

Resources to create with this skill:
- scripts/validators.py (stubs: validate_csv, validate_json, validate_xml; print “validators ready” on run)
- references/guide.md (sections: Schema, Naming, Async Task Orchestration with priority/retry/dependencies/concurrency/timeout/logging explained)
- assets/templates/README.md (describe mapping/transform templates and how to apply)
- onboarding/slides.md (internal onboarding: Title, Problem, Solution, Architecture, Workflow, Capabilities, Rollout Plan, Q&A)
- landing/landing.md (SEO-oriented draft for internal portal or external microsite)

Assumptions/ambiguities (document briefly where needed):
- Streaming ingestion: optional future capability; not required for v1 docs
- Default limits: concurrency=2, max_retries=3, timeout=30s (per task), backoff exponential with 5s base
- Sensitive data: default to tokenization for PII fields if configured; otherwise drop (document choice)

Key phrases to include in SKILL.md:
- Clear “Overview” (what/when to use)
- “Core Capabilities” with at least four sections (we propose six above)
- Brief workflow snippet with the words ingest, validate, transform, export in one place
- “Resources” describing scripts/, references/, assets/ (and refer to exact files created)