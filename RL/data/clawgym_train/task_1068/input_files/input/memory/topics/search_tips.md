# Hybrid Memory Search Tips

These notes summarize how to operate and tune the hybrid memory search.

## Weights at a Glance

Base fusion (when keyword overlap is normal):
- vector: 0.4
- keyword: 0.25
- header: 0.1
- filepath: 0.25

## Adaptive Weighting When Keyword Overlap Is Low

If the best keyword overlap across candidates is < 0.1, switch to:
- vector: 0.85
- keyword: 0.05
- header: 0.05
- filepath: 0.05

This adaptive weighting improves recall when the phrasing in notes differs from the query, or when the query uses synonyms or paraphrases.

## Temporal Routing

When a query includes an explicit date (e.g., “2026-04-15”), apply a 3.0× multiplier to the final score for candidates whose filepath includes that date string. This strongly prefers the daily note for that date while still considering other signals.

## Pseudo-Relevance Feedback (PRF)

If the top result’s base score is < 0.45 and no temporal routing is active, expand the query with a few salient terms extracted from top candidates (e.g., headers, bigrams in repeating phrases). Re-score with the expanded query and record the PRF terms for transparency.

## Practical Checklist

- Use descriptive headers like “Onboarding Checklist”, “Decisions”, “Follow-ups”.
- Include project names and dates in file paths to help filepath matching.
- Keep noisy boilerplate out of large sections to keep chunk text focused.

## Examples

- Query: “How to tune hybrid memory search when keyword overlap is low”
  - Look for sections describing adaptive weighting and low-overlap thresholds.
  - Expect “adaptive weighting”, “< 0.1” and “0.85/0.05/0.05/0.05”.

- Query: “Notes from 2026-04-15 about onboarding checklist and decisions.”
  - Expect temporal routing to boost `memory/2026-04-15.md`.
  - Headers like “Onboarding Checklist” and “Decisions” should be present.