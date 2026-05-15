# Implementation Plan: text_reports

Objective
Implement a minimal, production-ready Python package per the spec with an implement-then-audit loop that includes simplify, harden, and spec read-only passes. Keep scope tight and within budget.

Project Structure (under output/)
- src/text_reports/__init__.py
- src/text_reports/report.py
- src/text_reports/cli.py
- tests/test_report.py
- README.md
- modified_files.json
- audit/round1_simplify.md
- audit/round1_harden.md
- audit/round1_spec.md
- report.md

Tasks (Phase 1: Implement)
1) Module scaffolding
- Create package directories and __init__.py with module docstring and minimal exports.

2) report.py
- Implement parse_csv(path: str) -> list[dict]
  - Validate input path
  - Use csv.DictReader with newline="" and UTF-8
  - Trim header and values
  - Raise ValueError with clear messages for invalid cases
- Implement compute_metrics(rows: list[dict]) -> dict
  - Validate rows shape and consistent keys
  - Infer numeric columns (all non-empty parsable as float)
  - Compute count, sum, mean, min, max per numeric column
  - Produce metrics dict {total_rows, column_count, columns, numeric_summary}
- Implement render_markdown(metrics: dict) -> str
  - Validate required keys and types
  - Produce deterministic Markdown with:
    - "# Report Summary"
    - "## Overview"
    - "## Numeric Columns" with table or "No numeric columns detected."
  - Round floats to 2 decimals in output only

3) CLI
- argparse with --input/-i, -h/--help
- On success, print Markdown to stdout
- On error, print concise message to stderr and exit 1
- Add module docstring

4) Tests (pytest)
- test_parse_csv_valid_and_errors
- test_compute_metrics_numeric_and_mixed
- test_render_markdown_sections_and_table_header
- test_cli_help_output

5) Documentation
- README.md with:
  - How to compile/type-check (python -m py_compile)
  - How to run tests (pytest)
  - How to run CLI example

Quality Gates
- Module docstrings at top of each Python file (within first 5 non-empty lines)
- At least one explicit raise in report.py for invalid input
- No "TODO" or "FIXME" strings anywhere in src or tests
- Deterministic float formatting to 2 decimals in Markdown

Phase 2: Audit Loop (up to 3 rounds)
- After implementation, collect modified files list into output/modified_files.json (paths relative to output/)
- Spawn three read-only auditor passes (simulated via logs) with the explicit scoped file list:
  - simplify-auditor: clarity, dead code, naming, control flow
  - harden-auditor: validation, error handling, input sanitization, resilience
  - spec-auditor: conformance to this spec and acceptance criteria
- Each auditor produces a Markdown log under output/audit/roundX_<auditor>.md with:
  - "Files to review:" section listing the modified files
  - At least one finding using required fields:
    - "File and line number", "Category", "What's wrong", "Severity"
    - For harden also include "Attack vector" when applicable
    - "Fix recommendation" with a concrete patch suggestion
  - "Out-of-scope observations" section

Fix Strategy and Budget
- Process findings:
  - Critical/high: fix
  - Medium: fix in next round if clearly necessary
  - Low/cosmetic: fix inline only if trivial; otherwise exit on low-only round
- Refactor gate: only accept refactors that are clearly necessary (avoid style-only churn)
- Budget cap: Track cumulative fix-round diff growth and keep ≤30% over initial implementation diff
- If a non-initial round occurs, include a document pass: add up to 5 short inline comments explaining non-obvious original implementation choices (do not comment on the audit fixes themselves)

Exit Conditions
- Clean audit (zero findings)
- Low-only round (fix inline and exit without re-audit)
- Loop cap reached (3 rounds); fix remaining critical/high; document unresolved medium/low with reasons

Verification Steps (local)
- Compile/type-check:
  - python -m py_compile output/src/text_reports/*.py
- Run tests:
  - pytest -q
- CLI smoke test:
  - python -m text_reports.cli --help
  - python -m text_reports.cli --input path/to/sample.csv

Deliverables Checklist
- Code and tests created under output/ paths
- modified_files.json listing all created/modified files relative to output/
- Audit round 1 logs for simplify, harden, spec
- report.md with "Hardening Summary" including:
  - "Audit rounds completed: X of 3 max"
  - "Exit reason:" one of [Clean audit, Low-only round, Loop cap reached]
  - "Findings by round" with per-auditor counts and severities
  - "Actions taken" (what fixed, what skipped, document pass notes)
  - "Unresolved" (if any, with reasons)
  - "Out-of-scope observations"
  - "Budget" section mentioning staying within a <=30% cap

Notes
- Keep implementation simple and robust with clear error messages.
- Do not introduce any external libraries.
- Ensure stdout/stderr behavior is predictable for the CLI.