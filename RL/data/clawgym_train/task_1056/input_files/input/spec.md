# Feature Spec: text_reports Package

Goal
Build a small, production-ready Python package that parses a CSV file, computes simple dataset metrics, and renders a human-readable Markdown summary. Provide a CLI that accepts an input CSV path and prints the Markdown summary to stdout. Include basic input validation, explicit error handling, and unit tests.

Package Name
text_reports

Target Python Version
Python 3.11+

Dependencies
- Standard library only (csv, argparse, sys, io, math, pathlib, typing). No external packages.

Public API
1) parse_csv(path: str) -> list[dict]
- Reads a CSV file from an absolute or relative path.
- Returns a list of row dictionaries keyed by header names (using csv.DictReader).
- Trims leading/trailing whitespace from header names and values.
- Treats empty strings as missing values.
- Validation and error handling:
  - Raises ValueError if:
    - path is not a non-empty string,
    - file does not exist or is not readable,
    - the CSV has no header row,
    - the CSV has zero data rows.
  - For file I/O errors, raise ValueError with a clear message that includes the underlying error text.

2) compute_metrics(rows: list[dict]) -> dict
- Computes dataset metrics from the parsed rows.
- Required behavior:
  - Validate that rows is a non-empty list of dicts with consistent keys.
  - Infer numeric columns:
    - A column is considered numeric if all non-empty values in that column can be parsed as float.
    - Missing values (empty string or None) are ignored for numeric checks and stats.
  - For each numeric column, compute:
    - count: number of non-missing numeric values
    - sum: float sum
    - mean: float average (sum / count) when count > 0; if count == 0, exclude the column from numeric summary
    - min: minimum of the numeric values
    - max: maximum of the numeric values
  - Global metrics:
    - total_rows: integer
    - column_count: integer
    - columns: list of column names in the order read from the CSV header
    - numeric_summary: dict mapping column name -> {count, sum, mean, min, max}
- Validation and error handling:
  - Raises ValueError if:
    - rows is empty,
    - any element is not a dict,
    - keys are inconsistent across rows,
    - header keys are empty/blank.
  - Rounding and formatting should be done in rendering, not in this function.

3) render_markdown(metrics: dict) -> str
- Renders a Markdown report from the metrics dict produced by compute_metrics.
- Required sections and structure:
  - Top-level header: "# Report Summary"
  - "## Overview" section with:
    - Total rows
    - Column count
    - Comma-separated columns list
  - "## Numeric Columns" section with a Markdown table in the exact header format:
    | Column | Count | Sum | Mean | Min | Max |
  - For float presentation, round to 2 decimal places in the Markdown output.
  - If there are no numeric columns, still render the "## Numeric Columns" section and show a sentence "No numeric columns detected." (no table).
- Validation and error handling:
  - Raises ValueError if:
    - required top-level keys are missing (total_rows, column_count, columns, numeric_summary),
    - types are not as expected.

CLI Requirements
- Module: text_reports.cli
- Behavior:
  - Provide a CLI entrypoint that accepts an --input (or -i) CSV path and prints the Markdown summary to stdout.
  - Provide -h/--help output including a short usage description.
  - On invalid input (e.g., file not found, invalid CSV), print a concise error message to stderr and exit with a non-zero status.
  - Successful execution prints only the Markdown to stdout and exits zero.
- Usage example:
  python -m text_reports.cli --input sample.csv

Input Validation and Error Handling
- Include explicit raises (ValueError) for invalid arguments and malformed data in parse_csv, compute_metrics, and render_markdown.
- Do not crash with unhandled exceptions for predictable user errors; wrap file I/O with clear ValueError messages that include context.

Testing Requirements
- Create unit tests that cover:
  - parse_csv: valid CSV, missing file, empty data
  - compute_metrics: numeric and non-numeric columns, missing values, inconsistent keys error
  - render_markdown: correct sections and table header rendering; "no numeric columns" case
  - CLI: basic help (-h/--help) returns usage text; an invocation path can be smoke-tested by constructing metrics via the three functions (if needed) or verifying help output only.
- Tests must not rely on external files except those created in test fixtures or temporary directories.

Code Quality Gates
- Each Python source file in src/text_reports must begin with a module docstring (triple-quoted string in the first 5 non-empty lines).
- No "TODO" or "FIXME" strings anywhere in src or tests.
- At least one explicit raise for invalid input must appear in src/text_reports/report.py.
- Keep functions small and readable; prefer early returns over deep nesting.

Markdown Output Example (illustrative)
Input CSV:
name,age,height
Alice,30,65.1
Bob,,
Carol,28,62.4

Expected numeric columns: age, height

Sample Markdown structure:
# Report Summary

## Overview
- Total rows: 3
- Column count: 3
- Columns: name, age, height

## Numeric Columns
| Column | Count | Sum | Mean | Min | Max |
|---|---:|---:|---:|---:|---:|
| age | 2 | 58.00 | 29.00 | 28.00 | 30.00 |
| height | 2 | 127.50 | 63.75 | 62.40 | 65.10 |

Acceptance Criteria
- Deliverables under output/:
  - output/src/text_reports/__init__.py
  - output/src/text_reports/report.py
  - output/src/text_reports/cli.py
  - output/tests/test_report.py
  - output/README.md (must mention how to compile/type-check and how to run tests with exact commands)
  - output/modified_files.json (JSON array of modified files, paths relative to output/)
  - output/audit/round1_simplify.md, output/audit/round1_harden.md, output/audit/round1_spec.md (auditor logs for round 1)
  - output/report.md (final hardening summary)
- Implement-then-audit loop with three read-only auditors (simplify, harden, spec) per round, scoped to the modified files list.
- Exit when: clean audit (zero findings), or low-only findings (fix inline and exit), or loop cap of 3 rounds reached with all critical/high fixed.
- Budget: track cumulative diff growth and keep fix rounds within <=30% growth on top of original implementation diff.

Constraints
- Standard library only.
- Clean, deterministic output formatting (2 decimal places for floats).
- Stable behavior across platforms (newline handling tolerant).

Non-Goals
- No CSV writing.
- No plotting or external report formats.
- No concurrency, network calls, or databases.