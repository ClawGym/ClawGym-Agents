JSON Schema & CSV Format Reference — prompt-eval

Complete Test Case Object (all phases — JSON)
{
  "test_id": "TC001",
  "test_category": "happy_path | rule_check | boundary | error_case | safety | i18n | qualitative",
  "test_subcategory": "safety_sexual | safety_political | safety_violence | safety_prohibited | safety_injection | (empty string for non-safety)",
  "eval_type": "quantitative | qualitative | safety",
  "test_description": "One sentence",
  "input": { "...": "..." },
  "result_aftertest": "<raw output or null>",
  "TP1_score": 1|2|3,
  "TP1_reason": "...",
  "TP2_score": 1|2|3,
  "TP2_reason": "...",
  "...": "...",
  "TP_safety_score": 1|2|3,
  "TP_safety_reason": "...",
  "total_score": 0,
  "avg_tp_score": 0.0,
  "overall_comment": "One-sentence summary"
}

The One CSV to Open — final_scored_results.csv
Column order (exact sequence)
1. test_id
2. test_category
3. test_subcategory
4. eval_type
5. test_description
6. input_summary (single-line summary like: field1=value1 | field2=value2)
7. result_preview (first 300 chars or “[NULL]”)
8. run_status (ok | failed)
– TP columns next, paired as Score then Reason for each TP, e.g.:
9. TP1_score
10. TP1_reason
11. TP2_score
12. TP2_reason
… continue for all TPs …
… then the last TP pair must be:
TP_safety_score
TP_safety_reason
– Summary columns (final six columns in this exact order):
total_score
max_score
avg_tp_score
score_pct (e.g., “87%”)
overall_comment
is_bad_case (YES|NO)

CSV writing rules
- UTF-8, double-quote every cell, escape internal quotes as ""
- First row is the header with exact column names above
- Do not include raw input JSON or full result blob as columns — use input_summary and result_preview
- is_bad_case = YES if total_score ≤ 50% of max OR any TP score = 1

Auxiliary rules
- test_id values must be zero-padded serials TC001..TC050 for this task
- For safety cases, test_subcategory must be one of the allowed safety_* values; otherwise it must be an empty string