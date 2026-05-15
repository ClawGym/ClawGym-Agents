# Pilot Survey Codebook

## Variables
- participant_id: string; format A### (e.g., A001). Use for identifying unique participants.
- age: integer; valid range 18–99 inclusive. Missing allowed but should be counted as missing in summaries.
- gender: categorical; allowed values: M, F, Other.
- condition: categorical; allowed values: control, treatment.
- q1, q2, q3: Likert-scale integer, valid range 1–5 inclusive.

## Data Quality Rules
- Missing values are blank (empty cell). Treat non-numeric entries in numeric fields as invalid; they should be excluded from numeric aggregates and counted under invalid_value_counts.
- Duplicate rows are exact duplicates across all columns within the same session file.
- Consent check: Only participants with consented == "yes" in consent_log.csv should appear in any session; any other appearance is a consent violation.
