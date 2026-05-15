Order Metrics and CLI Specification
Version: 1.0

Overview
- Implement a small Python package (standard library only) and CLI that reads a CSV of orders and computes daily- and customer-level metrics.
- The CLI must:
  - Require a path to an orders CSV.
  - Optionally write the computed metrics to a JSON file via --json <path>.
  - Print a concise, human-readable summary to stdout.
- The JSON output must include top-level keys totals, by_day, and by_customer, following the schemas below.

CSV Input Schema
- File format: UTF-8 CSV, comma-separated, header row present.
- Columns (required):
  1) order_id (string)
  2) customer_id (string)
  3) order_date (string, format YYYY-MM-DD)
  4) status (string; values include paid, cancelled, refunded, pending; case-insensitive)
  5) quantity (integer; expected > 0)
  6) unit_price (decimal number; expected >= 0)
  7) discount (decimal number; expected >= 0; absolute amount deducted from order total)
- Additional/unknown columns may be present and must be ignored.
- Whitespace around fields should be trimmed.
- Rows with missing required fields or unparseable numbers should be skipped (not cause a crash).

Inclusion Rules
- Only include orders with status == "paid" (case-insensitive) in all metrics.
- Exclude orders with statuses such as "cancelled", "refunded", "pending", or any other non-"paid" value.
- If quantity <= 0, unit_price < 0, or discount < 0, skip the row.
- A “customer” is counted only if they have at least one included (paid) order.
- A “day” is counted only if it has at least one included (paid) order.

Per-Order Revenue Calculation
- Compute per-order revenue as:
  revenue = (quantity * unit_price) - discount
- Clamp negative revenue to zero if it occurs after calculation.
- Round per-order revenue to two decimal places using Python’s round(value, 2).
- Sum totals using per-order revenue values (post rounding to two decimals).
- Final aggregated revenues (totals and per-group) must be rounded to two decimals.

Aggregations to Produce
1) Totals (entire included set):
   - num_orders: total count of included (paid) orders.
   - total_revenue: sum of per-order revenues across all included orders, rounded to two decimals.
   - num_days: count of unique dates (order_date) that have >=1 included order.
   - num_customers: count of unique customers with >=1 included order.

2) By Day (by_day):
   - Keyed by order_date (YYYY-MM-DD).
   - For each day:
     - num_orders: count of included orders on that date.
     - total_revenue: sum of per-order revenue for that date, rounded to two decimals.
     - unique_customers: count of distinct customers with included orders that date.

3) By Customer (by_customer):
   - Keyed by customer_id (string).
   - For each customer:
     - num_orders: count of included orders for that customer.
     - total_revenue: sum of per-order revenue for that customer, rounded to two decimals.
     - first_order_date: earliest order_date among that customer’s included orders (YYYY-MM-DD).
     - last_order_date: latest order_date among that customer’s included orders (YYYY-MM-DD).
   - Only include customers with at least one included (paid) order.

JSON Output Schema
- Top-level JSON object with keys:
  {
    "totals": {
      "num_orders": <int>,
      "total_revenue": <number>,
      "num_days": <int>,
      "num_customers": <int>
    },
    "by_day": {
      "<YYYY-MM-DD>": {
        "num_orders": <int>,
        "total_revenue": <number>,
        "unique_customers": <int>
      },
      ...
    },
    "by_customer": {
      "<customer_id>": {
        "num_orders": <int>,
        "total_revenue": <number>,
        "first_order_date": "<YYYY-MM-DD>",
        "last_order_date": "<YYYY-MM-DD>"
      },
      ...
    }
  }
- JSON object key order is not significant.
- Numbers may be encoded as JSON numbers (floats). All revenues must be rounded to two decimals.

CLI Behavior
- Usage: python3 -m orders.cli <path/to/orders.csv> [--json <path/to/metrics.json>]
- Required positional argument: path to CSV.
- Optional flag --json writes the full metrics JSON to the provided path (directories must exist).
- Stdout should print a concise single-line summary of the form:
  Orders: <num_orders> | Revenue: <total_revenue> | Days: <num_days> | Customers: <num_customers>
- Exit code 0 on success. Non-zero (and a clear error message to stderr) on file not found or unreadable CSV.
- Do not require any non-standard-library dependencies.

Edge Cases and Error Handling
- Blank lines in CSV: ignore.
- Unknown statuses: treat as non-included (i.e., exclude).
- Duplicate order_id rows: the file provided does not contain intentional duplicates; if encountered, process each row independently (no special de-duplication).
- Dates:
  - order_date is a date only (no time zone). Treat as a simple string in YYYY-MM-DD validated minimally (must be 10 chars and look like a date); invalid dates should cause the row to be skipped.
- Numeric parsing:
  - quantity parsed as int; unit_price and discount as float or Decimal (both are allowed from the standard library). Apply rounding rules as specified above.
- Negative intermediate revenue values should be clamped to zero before rounding.
- Only “paid” orders count toward any aggregation.

Acceptance Criteria (for validation)
- The produced JSON must include the keys totals, by_day, by_customer.
- In totals:
  - num_orders and total_revenue must be present and numeric.
- The contents of totals, by_day, and by_customer must match the recomputation per this spec on the provided input/orders.csv.
- Tests must import compute_metrics(rows) (or similarly named) from the orders.metrics module.
- The CLI must run successfully on input/orders.csv and be able to write to output/metrics.json.

Worked Example (from provided CSV)
- For the provided input/orders.csv:
  - Expected totals:
    - num_orders = 9
    - total_revenue = 313.97
    - num_days = 5
    - num_customers = 6
  - Example by_day:
    - "2025-03-01": num_orders 2, total_revenue 54.99, unique_customers 2
    - "2025-03-02": num_orders 1, total_revenue 30.00, unique_customers 1
    - "2025-03-03": num_orders 2, total_revenue 60.00, unique_customers 2
    - "2025-03-04": num_orders 2, total_revenue 113.99, unique_customers 2
    - "2025-03-05": num_orders 2, total_revenue 54.99, unique_customers 2
  - Example by_customer (subset):
    - "cust_a": num_orders 3, total_revenue 84.98, first_order_date "2025-03-01", last_order_date "2025-03-05"
    - "cust_b": num_orders 2, total_revenue 40.00, first_order_date "2025-03-01", last_order_date "2025-03-03"
    - Only customers with at least one paid order appear.

Implementation Notes
- Use only the Python standard library (csv, json, argparse, datetime, decimal, etc.).
- Round per-order revenues to 2 decimals before summing; round aggregates to 2 decimals as the final step.
- Keep I/O (CLI) and computation (metrics) separate for testability.