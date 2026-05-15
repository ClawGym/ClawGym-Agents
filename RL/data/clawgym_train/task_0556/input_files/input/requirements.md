Transaction Reporting Tool — Requirements

Context
You will build a small Python library and a thin CLI to summarize transaction data from a CSV file into a structured JSON report.

CSV format
- File encoding: UTF-8 with a single header row.
- Columns (in order): date, amount, category, description
  - date: ISO format YYYY-MM-DD (e.g., 2025-02-10)
  - amount: decimal number using dot as separator; can be positive (income) or negative (expense)
  - category: non-empty string (e.g., Groceries, Salary)
  - description: free text; may contain spaces and commas (will be quoted by CSV if needed)
- The provided dataset is clean (no blank rows, no malformed fields). You may ignore advanced validations for this assignment.

Report requirements
- Library function: generate_report(csv_text: str) -> dict
  - Input: the entire CSV content as a string.
  - Output: a dictionary with the shape:
    {
      "monthly": {
        "YYYY-MM": {
          "categories": { "<category>": <number>, ... },
          "total": <number>
        },
        ...
      },
      "overall": {
        "categories": { "<category>": <number>, ... },
        "total": <number>
      }
    }
  - Behavior:
    - Group transactions by month using the first 7 chars of date (YYYY-MM).
    - Sum amounts per category within each month.
    - Compute each month’s overall total as the sum of that month’s category totals (equivalently, the sum of all amounts in that month).
    - Compute an overall summary across all months with category totals and an overall total.
    - Numeric totals must be numbers (not strings). Rounding to two decimal places is acceptable.
    - Preserve category casing as it appears in the CSV.
- CLI: output/src/cli.py
  - Accepts flags: --input <csv_path> and --output <json_path>.
  - Reads the CSV file from --input, uses generate_report to compute the report, and writes the JSON to --output.
  - Output JSON must contain top-level keys monthly and overall; overall must include a numeric total; each month entry must include categories and total.
  - Use only Python standard library (argparse, csv, json, decimal or similar). No external dependencies.

Constraints
- Language: Python 3.10+.
- Dependencies: standard library only (no pandas, no third-party packages).
- I/O: Do not read network resources. Only process local input CSV and write local JSON.
- Structure: Keep the library small and well-structured; keep the CLI thin.
- Performance: The provided dataset is small; prioritize clarity over micro-optimizations.
- Robustness: You may assume the provided CSV is clean, but your parser should still ignore surrounding whitespace and handle typical CSV quoting.

Acceptance criteria
- A function generate_report(csv_text: str) exists and returns a dict in the required shape.
- The computed report groups by month (YYYY-MM), sums per-category and month totals correctly, and includes an overall section with category totals and an overall total.
- The CLI accepts --input and --output and writes a valid JSON file that includes monthly and overall as described.
- The output/demo/report.json produced from the provided sample dataset loads as valid JSON and includes at least one month key matching YYYY-MM, with categories and total present, and overall.total is numeric.
- At least one minimal test exists that calls generate_report on a small inline CSV or the sample data and asserts the presence of expected top-level keys and at least one month and category.
- Code uses only standard library and is readable and maintainable.

Non-goals
- No advanced currency conversion, tax rules, or multi-currency support.
- No interactive UI beyond the CLI flags.
- No persistence beyond writing the resulting JSON file.

Notes
- You may use Decimal to avoid floating-point precision issues, but final JSON must contain numeric types (floats are acceptable).
- Ordering of months or categories is not mandated, but stable ordering is appreciated where easy.