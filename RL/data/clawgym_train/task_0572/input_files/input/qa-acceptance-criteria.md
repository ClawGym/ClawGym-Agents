# QA Acceptance Criteria: import-contacts CLI

This document defines acceptance criteria, edge cases, and expected observable behaviors for the `contacts import-contacts` subcommand. All tests should be automatable with pytest and designed to run in isolation with temporary files and SQLite databases.

## Functional Criteria

1. CLI Argument Parsing
   - Running with no arguments prints usage and exits with code 1.
   - Running with a non-existent CSV path prints an error to stderr and exits with code 1.
   - `--db PATH` changes the target database path; if the file doesn’t exist, it is created.
   - `--delimiter` and `--encoding` are respected for CSV parsing.

2. Database Initialization
   - On first run against a new `--db`, the tool creates the `contacts` table with columns and constraints exactly as specified:
     - id (INTEGER PK AUTOINCREMENT), email (TEXT UNIQUE NOT NULL), first_name, last_name, phone, company, tags, created_at (TEXT NOT NULL), updated_at (TEXT NOT NULL).
   - The schema must enforce uniqueness on `email`.

3. Validation
   - Required header `email` must exist (case-insensitive). If absent, print a clear error and exit with code 1.
   - Email must match the regex. Invalid emails cause the row to be skipped; error recorded as `invalid_email`.
   - Missing email causes skip; error recorded as `missing_email`.
   - Phone must normalize to 7–20 characters (digits plus optional leading `+`); otherwise `invalid_phone`.
   - More than 10 tags in a row → `too_many_tags`.
   - Tag length > 64 → `tag_too_long`.
   - `first_name`, `last_name`, or `company` length > 128 → `field_too_long`.

4. Normalization
   - Emails lowercased and trimmed.
   - Tags are split on `,` or `;`, trimmed, deduped, sorted, and joined by comma for storage.
   - Empty strings are stored as NULL (except `email` which is required).
   - Phone digits and optional leading `+` retained; punctuation/spaces removed.

5. Deduplication and Upsert
   - Input-level: when the same email appears multiple times in the same CSV, only the last occurrence participates in DB write semantics (“last-one-wins”). Earlier duplicates counted as `skipped_duplicates`.
   - DB-level with `--on-duplicate skip`: if email exists, do not modify; increment `skipped_duplicates`.
   - DB-level with `--on-duplicate update` (default): update existing row with incoming fields if any field value actually differs post-normalization; otherwise no-op and do not increment `updated`.

6. Dry-Run Semantics
   - `--dry-run` prevents any DB writes/changes.
   - Counts in summary (inserted/updated/skipped_duplicates/invalid) reflect what would happen without actually modifying the DB.
   - Dry-run should still create the DB schema if the DB file didn’t exist? NO. In dry-run, the tool must NOT create or modify the database file at all. It should only read it if present to evaluate duplicate detection; if DB is missing, assume empty DB for counting purposes.
   - Final summary must include `dry_run=true`.

7. Logging Summary
   - At the end of execution, print a single-line summary exactly in this format (spacing and key order are significant for tests):
     - `Import summary: total=<int>, parsed=<int>, valid=<int>, inserted=<int>, updated=<int>, skipped_duplicates=<int>, invalid=<int>, dry_run=<true|false>, db="<path>"`
   - When `--report-json PATH` is provided, write a JSON file following the schema outlined in the feature spec. The file must include an `errors` array with each error containing `row`, `email` (or null), and `error` code.

8. Error Reporting
   - For each invalid row, write to stderr a line beginning with:
     - `ERROR: Row <n> (<email or '-'>): <reason>`
   - Exit code policy:
     - `0` if completed with zero invalid rows.
     - `2` if completed with one or more invalid rows (even if inserts/updates succeeded).
     - `1` if a fatal error occurs (e.g., missing `email` header, file open failure, database write failure in non-dry-run mode).

9. Idempotency
   - First run importing a valid CSV with new emails results in `inserted = N`, `updated = 0`.
   - Second run with the same CSV and `--on-duplicate update` results in `inserted = 0`, `updated = 0`, `skipped_duplicates = 0`, `invalid = 0`, exit code 0.
   - If a value changes in the CSV (e.g., `company`), the subsequent run counts those rows in `updated`, not `inserted`.

10. Quiet and Debug Modes
   - `--quiet` suppresses per-row logs and non-essential output but still prints the final summary unless `--report-json` is used; if both `--quiet` and `--report-json` are set, the summary may be suppressed while the JSON report is written.
   - `--log-level debug` prints detailed per-row decisions to stdout or stderr (implementation choice), but never breaks the exact final summary format.

## Edge Case Scenarios and Expected Outcomes

1. Missing Required Header
   - Input CSV has headers: `first_name,last_name,phone` (no `email`).
   - Command: `contacts import-contacts missing-email-header.csv`
   - Expected: stderr contains a clear message referencing missing `email` header; exit code 1; no DB created or modified.

2. Invalid Emails and Mixed Validity
   - CSV contains:
     ```
     email,first_name
     valid@example.com,Val
     invalid-email,Inv
     also@invalid,MissingTld
     ```
   - Expected:
     - `valid@example.com` inserted or updated according to DB state.
     - Two invalid rows reported with `invalid_email`.
     - Summary shows `invalid=2`.
     - Exit code 2.

3. Dry-Run with New Database
   - DB file does not exist.
   - Command: `contacts import-contacts sample.csv --dry-run --db tmp/new.db`
   - Expected:
     - No DB file created on disk.
     - Output shows counts as if inserts/updates would be performed (`inserted` equals count of unique valid emails not present in DB).
     - Summary includes `dry_run=true`, `db="tmp/new.db"`.
     - Exit code 0 if no invalid rows; 2 if any invalid rows.

4. Input-Level Duplicate Resolution
   - CSV includes two rows for the same email; second row differs in `company`.
   - With `--on-duplicate update`, only the last row’s data is considered for DB write; earlier occurrence counted in `skipped_duplicates`.
   - Summary reflects `skipped_duplicates` increment for the input duplicate (not the DB-level decision).

5. On-Duplicate Skip Behavior
   - With `--on-duplicate skip`, any email already present in DB is not modified and counted in `skipped_duplicates`. `updated` remains 0.

6. Tag Normalization Limits
   - A row with 12 tags should be invalid (`too_many_tags`) and skipped.
   - A row with a tag longer than 64 chars should be invalid (`tag_too_long`) and skipped.

7. Phone Normalization
   - A phone like `"(555) 12"` normalizes to fewer than 7 digits → `invalid_phone` and skipped.
   - A phone like `"+1 555 123 4567"` normalizes to `+15551234567` → valid.

8. Field Length Limits
   - `first_name` with 200 characters results in `field_too_long` and skipped.

9. Report JSON
   - When `--report-json out/report.json` is used, the file must exist at the end with:
     - Correct counts.
     - An `errors` array for all invalid rows with correct `row` indices (1-based including header? Row numbering starts at 2 for the first data row; header is row 1), correct `email` value (or null if missing), and correct `error` code.

10. Idempotent Re-Run
   - After inserting two valid rows, rerun the same CSV with `--on-duplicate update`:
     - Summary shows `inserted=0`, `updated=0`, `skipped_duplicates=0`, `invalid=0`.
     - Exit code 0.

## Summary Line Format (Strict)

Must match exactly one space after commas and specified key order:

`Import summary: total=<int>, parsed=<int>, valid=<int>, inserted=<int>, updated=<int>, skipped_duplicates=<int>, invalid=<int>, dry_run=<true|false>, db="<path>"`

- `total`: total lines including header? Definition:
  - `total` = number of data rows read (excluding header). 
- `parsed`: number of rows parsed before validation (should equal `total` unless lines are blank; blank lines should be ignored and not counted in `total`).
- `valid`: rows that pass validation and input-level deduplication (i.e., rows surviving “last-one-wins” logic).
- `inserted`: rows that would be or were inserted.
- `updated`: rows that would be or were updated (for `--on-duplicate update` when fields actually differ).
- `skipped_duplicates`: sum of earlier duplicates in CSV for the same email plus DB-level skips under `--on-duplicate skip`.
- `invalid`: rows that failed validation and were skipped.
- `dry_run`: literal `true` or `false`.
- `db`: the exact DB path string passed or defaulted.

## Non-Functional Criteria

- Deterministic behavior: running the same input file and options yields the same counts and summary text (timestamps excluded).
- Does not leak file handles; can run multiple times in the same process/tests reliably.
- Works on Linux, macOS, and Windows paths in tests (use Python stdlib only; no OS-dependent shells required).

## Example Commands and Expected Outcomes

1. Basic import:
   - `contacts import-contacts input/contacts.csv --db .data/contacts.db`
   - Expect: schema creation if needed, inserts for new emails, summary line with `dry_run=false`.

2. Dry-run import with JSON:
   - `contacts import-contacts input/contacts.csv --db .data/contacts.db --dry-run --report-json output/report.json`
   - Expect: `output/report.json` with counts; no DB file created if it didn’t exist; summary with `dry_run=true`.

3. Update existing:
   - First run inserts; second run with modified `company` for one email using `--on-duplicate update`:
   - Expect: `updated=1`, `inserted=0`.

4. Skip existing:
   - With `--on-duplicate skip` and two existing emails in DB:
   - Expect: `skipped_duplicates=2`, `updated=0`.

## Test Data Row Numbering

- Row numbering in errors starts at 2 for the first data row (header is row 1).
- Blank lines are ignored and not counted as rows.

## Prohibited Behaviors

- Creating or modifying the DB file during `--dry-run`.
- Changing the summary key order or spacing.
- Failing silently on invalid rows (must report).
- Modifying existing rows on `--on-duplicate skip`.

## Ready-for-Release Checklist

- [ ] All acceptance scenarios above have automated pytest tests.
- [ ] Exit codes conform to policy (0 no invalid, 2 with invalid, 1 fatal).
- [ ] Summary line format verified by regex tests.
- [ ] JSON report schema validated when `--report-json` is provided.
- [ ] Idempotency tests pass for both insert and update paths.