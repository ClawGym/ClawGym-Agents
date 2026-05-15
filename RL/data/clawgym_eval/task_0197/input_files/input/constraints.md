Instructions for processing input/opportunities.jsonl and producing outputs under output/:

1) output/ev_results.jsonl (one JSON object per valid opportunity, preserving input order)
- Validation:
  - Only drop records where p is provided and not in [0,1]. All other inputs are valid.
- Types and formulas:
  - type=basic:
    - Inputs: p, win, loss
    - b = win / loss
    - ev_value = p * win - (1 - p) * loss
    - ev_percentage = (ev_value / loss) * 100
    - kelly_fraction_half = max(0, ((p * b - (1 - p)) / b) / 2)
    - Do not include edge or ev_per_dollar
  - type=ratio:
    - Inputs: p, b (treat win=b, loss=1)
    - ev_value = p * b - (1 - p) * 1 = p * (b + 1) - 1
    - ev_percentage = ev_value * 100
    - kelly_fraction_half = max(0, ((p * b - (1 - p)) / b) / 2) = max(0, ev_value / (2 * b))
    - Do not include edge or ev_per_dollar
  - type=polymarket:
    - Inputs: your, market (market > 0 in our data)
    - edge = your - market
    - ev_per_dollar = edge / market
    - ev_value = edge
    - ev_percentage = edge * 100
    - Do not include Kelly field
- Verdict:
  - "positive" if ev_value > 0 (or edge > 0 for polymarket)
  - "negative" if ev_value < 0
  - "break-even" otherwise
- Rounding:
  - ev_value, edge, ev_per_dollar, kelly_fraction_half → 4 decimal places
  - ev_percentage → 2 decimal places

2) output/summary.json (single JSON object)
- Fields:
  - total_input (count all rows in input)
  - processed (count valid rows after dropping invalid p)
  - positives, negatives, break_even
  - top3_ids: three IDs with the highest ev_value in descending order
- For polymarket, use edge as ev_value for ranking.

3) output/recommendations.md (concise narrative)
- Briefly explain the top 3 picks (by ID) and why the EV is attractive.
- Include a short cautions section explicitly mentioning: "not financial advice", fees, slippage, and sample size risk.

Additional requirements:
- Preserve the input order for valid rows in ev_results.jsonl.
- Use only the fields and rounding rules specified here.
- Paths must be exactly:
  - output/ev_results.jsonl
  - output/summary.json
  - output/recommendations.md