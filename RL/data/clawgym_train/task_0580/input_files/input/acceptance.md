Acceptance Criteria for the Local Health Check Deliverables

Scope
- The agent must read this document and report_spec.yaml before producing outputs.
- All outputs must be written under output/ using only relative paths.

Required Files
1) output/top_processes.csv
   - Must exist and be a valid CSV with exactly one header row.
   - The header must contain exactly these columns in this order:
     id, device_name, application_name, cpu_usage, memory_usage, timestamp, day, week, month, working_day
   - At least 1 data row is required.
   - Field validations:
     - cpu_usage and memory_usage must be numeric (decimals allowed), and must not include symbols (e.g., no %).
     - timestamp must match the regex: ^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$ (example: 2026-04-17 14:05:00).
     - day must be an integer in [1..7] (ISO weekday).
     - month must be an integer in [1..12].
     - working_day must be either Weekday or Weekend.
   - The row content should reflect the most recent capture from the current run.
   - id values should start at 1 and increase by 1 for each row in the export.

2) output/alerts_summary.json
   - Must exist and be a valid JSON object with keys:
     - total_alerts (non-negative integer)
     - by_severity (object with keys Amber and Red, each a non-negative integer)
     - sample (array of 0 to 3 objects)
   - If sample is non-empty, each object must have the keys:
     alert (Amber|Red), date (string), devicename (string), type (CPU), variant (CPU)
   - If there is insufficient historical data to run a prediction, set:
     total_alerts = 0, by_severity.Amber = 0, by_severity.Red = 0, and sample = []
   - No additional top-level keys should be included.

3) output/monitoring_overview.md
   - Must exist and contain at least 120 words.
   - Must include the substrings “Methodology” and “Limitations” (case-insensitive).
   - Must explicitly mention both filenames: output/top_processes.csv and output/alerts_summary.json.
   - Should summarize:
     - What was done to collect metrics (e.g., scanning top CPU/memory processes).
     - How the CSV and JSON artifacts were derived.
     - Whether predictive analysis ran; if it did not run due to insufficient history, this must be stated clearly.
     - A brief interpretation of the findings.

Execution Guidelines
- Use local system information (e.g., via psutil) to capture CPU and memory usage.
- If possible, attempt a short-term CPU spike prediction using available historical data; otherwise, proceed without it and document the limitation.
- Persist collected metrics locally if your workflow requires a database, but all exported artifacts must be written under output/.

Quality and Consistency Checks
- No absolute or machine-specific paths should appear in any artifact content.
- Numeric fields must be parseable as numbers by standard CSV/JSON parsers.
- Ensure timestamps are consistently formatted.
- Ensure that the CSV represents the most recent capture from the current run (not stale or older data).
- Ensure that any alerts in the JSON are consistent with the predicted output (if prediction was run).

Failure Conditions
- Missing any required file under output/.
- Incorrect header order or missing columns in the CSV.
- Non-numeric cpu_usage or memory_usage.
- Invalid timestamp format or out-of-range day/month values.
- JSON schema violation (missing required keys, extra keys, or invalid sample entries).
- monitoring_overview.md under 120 words or missing required substrings/references.

Helpful Notes
- The “week” value in the CSV refers to the week-of-month logic used by the monitoring script ((day_of_month - 1) // 7 + 1) or equivalent.
- The “working_day” should be derived from the ISO weekday (1–5 => Weekday, 6–7 => Weekend).
- For alerts, “Amber” indicates moderate risk and “Red” indicates high risk. If your model outputs fine-grained scores, map them to these categories before export.