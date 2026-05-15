OpenClawBrain Maintenance Rules — Edge Tiers and Reflex Ratio

Edge Tier Thresholds
- reflex: weight >= 0.6
- habitual: 0.15 <= weight < 0.6
- dormant: weight < 0.15 (non-inhibitory; includes zero and small negative weights)
- inhibitory: weight < -0.01

Precedence
- If an edge weight is below the inhibitory threshold (< -0.01), classify it as inhibitory regardless of other tier ranges.

Reflex Ratio
- Definition: reflex_ratio = (count of non-inhibitory positive edges with weight >= 0.6) / (count of non-inhibitory positive edges with weight > 0)
- Notes:
  - “Non-inhibitory positive edges” are edges with weight > 0 and not classified as inhibitory (i.e., strictly positive).
  - Zero-weight edges (weight == 0) do not count as positive.
  - If there are zero non-inhibitory positive edges, set reflex_ratio to 0.0.
  - Round the final value to exactly 6 decimal places.