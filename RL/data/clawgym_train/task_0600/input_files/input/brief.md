# Product Brief — csvcut (Task ID: T-042)

Purpose
Extract selected columns from a CSV by header name or by 1-based index. Provide a tiny, dependency-free Python CLI that can be used in pipelines.

Scope
- Minimal, reliable CSV column selection
- Works with stdin or a file path
- Outputs CSV to stdout
- No external dependencies (use Python stdlib only)

Non-goals
- Not a full csvkit replacement
- No complex transformations (no type inference, no expressions)
- No multi-file joins or aggregations

Target users
- Developers and analysts who need a lightweight csv column selector for quick shell pipelines

Operational expectations
- Single-file script: csvcut.py (Python 3.8+)
- Use Python’s csv module (excel dialect by default)
- Stream processing: do not load entire file into memory
- Robust to common CSVs, including quoted fields and commas inside quotes
- Clear, helpful usage/help message
- Deterministic behavior with simple, explicit options

Core behaviors
- Selection by header names (default assumes first row is header)
- Selection by 1-based indices
- Order of output columns matches the order specified in -c/--columns
- Duplicate selections allowed and should be repeated in the output
- Missing column name or out-of-range index is an error with a helpful message; exit non-zero (2)
- If a row has fewer columns than a requested index, output an empty field for that position (do not crash)
- If misused (e.g., missing -c), show usage and exit with code 2
- Support --help/-h to print usage and exit 0
- Input path optional; if omitted or “-”, read from stdin
- Optional: --no-header flag to treat the first row as data; in this mode, selection is by indices only

CLI shape (minimal)
- Required: -c/--columns “list” (comma-separated tokens, each a header name or 1-based index; whitespace around tokens ignored)
- Optional: --no-header (first row is data, names are not allowed)
- Positional: INPUT_FILE (optional; “-” or omitted = stdin)

Examples (indicative)
- Select by names: echo "a,b,c\n1,2,3\n4,5,6" | python3 csvcut.py -c b,a
- Select by indices: python3 csvcut.py -c 3,1 sample.csv
- Mixed: python3 csvcut.py -c name,3,1 data.csv
- No header mode: python3 csvcut.py --no-header -c 2,1 rows.csv

Quality and UX
- Clear error messages (e.g., “unknown column: foo” or “index out of range: 7”)
- Exit codes: 0 on success; 2 on usage or selection errors
- README with concise usage, options, and examples
- Code comments for non-obvious choices

Paths and packaging
- Script: output/shared/artifacts/T-042/csvcut.py
- README: output/shared/artifacts/T-042/README.md
- Spec: output/shared/specs/T-042-spec.md
- Review: output/shared/reviews/T-042-review.md
- Optional decision note: output/shared/decisions/T-042-decision.md

Handoff expectations
- Builder handoff must include: what was done, artifact paths, how to verify, known issues, and next action
- Reviewer provides at least two findings and an explicit decision (Approved or Returned with next steps)

Notes
- Keep flags simple; do not add new flags unless necessary
- Default delimiter is comma; rely on csv module to handle quoting
- Ensure compatibility with Python 3.8+