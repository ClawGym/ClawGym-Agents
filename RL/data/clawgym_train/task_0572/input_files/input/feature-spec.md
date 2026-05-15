# Feature Specification: import-contacts CLI subcommand

Version: 1.0  
Owner: Data Tools Team  
Audience: Implementation + QA

## Overview

Build a Python-based CLI subcommand named "import-contacts" that ingests a CSV file of contacts, validates and normalizes records, deduplicates by email, and stores/upserts them into a local SQLite database. The command must support a dry-run mode, robust error reporting, and a concise summary at the end of execution. It must be idempotent and safe to run repeatedly.

Primary use case: teams regularly receive CSV exports of contact lists and need a reproducible way to ingest them into a single SQLite database with duplicate prevention and clear logs.

## Invocation

- Base command: `contacts import-contacts <csv_path> [options]`
- Description: Import contacts from a CSV file into a SQLite database with validation, deduplication, and upsert behavior.

Examples:
- `contacts import-contacts data/contacts.csv`
- `contacts import-contacts data/contacts.csv --db .data/contacts.db --dry-run`
- `contacts import-contacts data/contacts.csv --on-duplicate update --report-json output/report.json`

## CSV Schema

Required headers:
- email

Optional headers:
- first_name
- last_name
- phone
- company
- tags

Notes:
- Column names are case-insensitive; treat `Email`, `EMAIL`, etc. as `email`.
- Extra/unknown columns are ignored.
- The `tags` column can contain multiple tags separated by comma `,` or semicolon `;`.

Minimum viable CSV must include at least: `email`.

## Data Normalization

- Trim leading/trailing whitespace on all fields.
- Email:
  - Lowercase.
  - Must match basic pattern: `^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$`
- Phone:
  - Keep digits and leading `+` only; remove spaces, dashes, and parentheses.
  - Permitted length (after normalization): 7–20 characters (digits plus optional leading `+`).
- Tags:
  - Split on `,` or `;`.
  - Trim each tag, discard empty tags.
  - Store in DB as a comma-joined string with tags sorted alphabetically and de-duplicated.
- Company, first_name, last_name:
  - Store as-is after trimming (no forced case conversion).
- Empty strings should become NULL in the database (except email which is required).

## Validation Rules

- Required: `email` must be present and match the email regex.
- Optional fields, if present:
  - `phone` must satisfy normalization length rules (7–20) after cleaning.
  - `tags` as normalized list; no more than 10 tags; each tag max length 64.
  - `first_name`, `last_name`, `company` individual fields max length 128.
- Rows failing validation are skipped; errors are recorded for reporting.

## Deduplication & Upsert Behavior

- Deduplication key: email (unique).
- Input-level deduplication:
  - When the same email appears multiple times within the provided CSV, keep only the last occurrence for application (the “last-one-wins” rule).
  - Earlier duplicates are counted in `skipped_duplicates` if they differ from the last occurrence; only the final instance participates in DB write logic.
- Database-level behavior (controlled by `--on-duplicate`):
  - `skip` (behavior): If a row’s email already exists, do not modify existing record; count as `skipped_duplicates`.
  - `update` (default): If a row’s email exists, update fields with the incoming normalized values using the following rules:
    - Only overwrite fields present in the CSV row (None/empty in CSV should set NULL unless `--preserve-nonempty` is specified; not in scope for v1).
    - If the incoming normalized field values are exactly equal to the existing values, do not change the record and do not increment `updated` count (no-op).
- Uniqueness is enforced by a UNIQUE index on `email`.

## SQLite Storage

- Default DB path: `./contacts.db` unless `--db` is specified.
- Schema (single table):
  - Table: `contacts`
    - `id` INTEGER PRIMARY KEY AUTOINCREMENT
    - `email` TEXT NOT NULL UNIQUE
    - `first_name` TEXT NULL
    - `last_name` TEXT NULL
    - `phone` TEXT NULL
    - `company` TEXT NULL
    - `tags` TEXT NULL                (comma-separated, normalized as specified)
    - `created_at` TEXT NOT NULL      (ISO 8601 string: UTC; set when first inserted)
    - `updated_at` TEXT NOT NULL      (ISO 8601 string: UTC; set on insert and each real update)
- On first run against a new DB, migration must create this schema.
- Timezone handling: store timestamps as UTC ISO 8601 without timezone suffix, e.g., `2026-04-17T12:34:56`.

## Options / Flags

- `--db PATH`:
  - SQLite database file path (default `./contacts.db`).
- `--dry-run`:
  - Do not perform any write to the database.
  - Still parse and validate all rows; compute and print summary as if writes occurred.
- `--on-duplicate {update,skip}`:
  - Default: `update`.
  - Behavior as defined above.
- `--delimiter CHAR`:
  - CSV delimiter (default `,`).
- `--encoding NAME`:
  - File encoding (default `utf-8`).
- `--report-json PATH`:
  - If provided, write a JSON report file with summary and errors at this path.
- `--log-level {info,debug,warning}`:
  - Default `info`.
  - `debug` should include per-row validation decisions in logs.
- `--quiet`:
  - Suppress non-essential output; still print final summary unless `--report-json` is provided (then summary can be suppressed when quiet is set).

Out of scope for v1:
- Networked databases, concurrency controls, or partial commit strategies.

## Output & Logging

- Final summary printed to stdout (unless suppressed by `--quiet`):
  - Format (single line):
    - `Import summary: total=<int>, parsed=<int>, valid=<int>, inserted=<int>, updated=<int>, skipped_duplicates=<int>, invalid=<int>, dry_run=<true|false>, db="<path>"`
- If `--report-json` is set, write a JSON file with structure:
  ```
  {
    "total": int,
    "parsed": int,
    "valid": int,
    "inserted": int,
    "updated": int,
    "skipped_duplicates": int,
    "invalid": int,
    "dry_run": bool,
    "db_path": "string",
    "errors": [
      { "row": int, "email": "string|null", "error": "invalid_email|missing_email|invalid_phone|too_many_tags|tag_too_long|field_too_long" }
    ]
  }
  ```
- Row-level validation errors:
  - Printed to stderr prefixed with `ERROR: Row <n> (<email or '-' if missing>): <reason>`.
  - Reasons must align with `error` values above.
- Logging:
  - At `info` level: only high-level progress and the final summary.
  - At `debug` level: include per-row decisions (e.g., “duplicate in CSV, keeping last occurrence for email foo@bar.com”).

## Exit Codes

- `0`: Completed without validation errors (all valid), even if zero rows found (empty file).
- `2`: Completed with one or more validation errors (some rows skipped but overall run finished).
- `1`: Fatal error (e.g., file cannot be read, missing required header `email`, SQLite error on schema/migration).

## Idempotency

- Running the same CSV multiple times with `--on-duplicate update`:
  - First run: inserts new records; `inserted = N`.
  - Second run: if CSV data hasn’t changed, no updates should occur; `inserted = 0`, `updated = 0`.
  - If the second run modifies a field for an existing email (e.g., changed `company`), then `updated` increments accordingly.

## Performance & Memory (non-blocking guidance)

- The tool may load the file iteratively (streaming reader) to handle large files.
- For v1, simple iteration is fine; batch sizes, transactions, and indices are permitted but not required by tests.

## Sample CSV (for reference)

```
email,first_name,last_name,phone,company,tags
alice@example.com,Alice,Anderson,+1 (555) 111-2222,Example Inc,"alpha; beta"
bob@example.com,Bob,,555-333-4444,,sales,lead
bob@example.com,Bobby,Barker,555-333-4444,BB Co,"lead"
invalid-email,,Doe,123,Acme,""
,NoEmail,Person,,,
```

Expected handling (high level):
- `alice@example.com`: valid, inserted.
- `bob@example.com`: two rows; keep the last (Bobby Barker, BB Co); insert/update logic per DB state.
- `invalid-email`: invalid email → skipped and counted in `invalid`.
- Missing email row: skipped with `missing_email` error.

## Security & Reliability Notes

- Do not execute arbitrary code or external processes based on CSV content.
- Ensure the DB directory exists or fail gracefully with a descriptive error.
- Handle incorrect encoding with a clear error message suggesting `--encoding`.

---