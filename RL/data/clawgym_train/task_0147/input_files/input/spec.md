# CSV → JSON Utility — Functional Spec

Author: Platform Tools
Target: Python 3 (standard library only)
Encoding: UTF-8

Overview
- Build a small, production-quality CLI utility that converts CSV into JSON following strict parsing and normalization rules.
- Provide two callable functions and a CLI entry point.
- The first non-blank line of the file is the header row. All subsequent blank or whitespace-only lines must be ignored.

Required API
- transform_csv_to_json(csv_text: str) -> list[dict]
  - Accepts raw CSV text.
  - Returns a list of dictionaries, one per data row.
- load_csv_and_write_json(in_path: str, out_path: str) -> None
  - Loads CSV from in_path (UTF-8), transforms with transform_csv_to_json, and writes UTF-8 JSON to out_path with an array of objects, pretty or compact is acceptable.

CLI Usage
- Run as: python output/tools/csv_to_json.py input.csv output.json
- The CLI must:
  - Read the CSV from input.csv (UTF-8 with universal newlines).
  - Write JSON to output.json (UTF-8).
  - Exit 0 on success; print a brief error message and exit non-zero on failure.

Parsing Rules
1) Headers
- The first non-blank, non-whitespace-only line in the CSV is the header row.
- Split headers using standard CSV rules (commas, double quotes).
- Trim leading/trailing whitespace from header names.
- Headers must be unique. If duplicates appear after trimming, suffix subsequent duplicates with _2, _3, ... in order of appearance.

2) Rows
- Ignore blank/whitespace-only lines anywhere in the file.
- Parse rows with Python’s csv module (comma delimiter, double quote support).
- After parsing, trim leading and trailing whitespace from each cell’s value.
- If a row has fewer cells than headers, treat missing cells as null.
- If a row has more cells than headers, ignore extras beyond the header count.

3) Value Normalization (per cell, after trimming)
- Case-insensitive "null" → JSON null (e.g., "null", "NULL", "NuLl" all map to null).
- Empty cell (empty string after trimming) → JSON null.
- Numeric-looking values convert to numbers:
  - Integers: optional leading sign, digits only (e.g., "42", "-7", "+006" → 42, -7, 6).
  - Floats: optional leading sign, digits with a decimal point (e.g., "5.0", "0.75", "-3.14" → float).
  - Optional scientific notation may be treated as float when using float() (e.g., "1e3" → 1000.0) but is not required for input correctness tests.
- All other values remain strings (after trimming). Quotes used in CSV are for parsing and must not remain in the final value.

4) JSON Output
- Output is a JSON array of objects in the same row order as the CSV (excluding blank lines).
- Keys are header names (post-deduplication and post-trim).
- Values are normalized according to the rules above.
- File should be valid JSON and readable by standard tools.

Error Handling
- The utility must not crash on:
  - Trailing blank lines,
  - Rows with missing cells,
  - Values with leading/trailing spaces,
  - Case variants of "null".
- Failures should be rare; if a file cannot be read/written, print a concise error to stderr and exit non-zero.
- For malformed CSV (unbalanced quotes), bubble up a clear error message and exit non-zero.

Implementation Notes
- Use only the Python standard library (csv, json, io, sys, argparse/os/pathlib acceptable).
- Prefer csv.reader with appropriate settings; consider skipinitialspace=False (defaults) and manually strip values after parsing.
- When converting numbers, attempt int first, then float as a fallback; if both fail, keep as string unless "null" rules apply.

Example
CSV:
id,name,age,height,notes
1, Alice , 30 , 5.5 , "  likes tea "
2,Bob, null , 6 ,   

JSON (array pretty-printed for clarity):
[
  {"id": 1, "name": "Alice", "age": 30, "height": 5.5, "notes": "likes tea"},
  {"id": 2, "name": "Bob", "age": null, "height": 6, "notes": null}
]

Test Expectations (minimum)
- Ignores blank/whitespace-only lines (no extra empty objects).
- Trims leading/trailing whitespace from headers and cells.
- Converts numeric-looking values to numbers (ints/floats).
- Maps case-insensitive "null" to JSON null.
- Treats empty cells as JSON null.
- Handles missing cells gracefully without IndexError.

Deliverables Recap
- Implement the two functions and CLI exactly as specified.
- Provide tests validating blank-line handling, trimming, numeric conversion, and "null" mapping.