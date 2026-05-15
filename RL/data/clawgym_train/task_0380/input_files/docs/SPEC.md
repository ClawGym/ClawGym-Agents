# Quality Score Specification (Business Perspective)

This document describes the intended business formula for computing a per-review quality score.

- Base points: rating (1–5) scaled by 20. Example: rating=4.0 -> 80 points.
- Defect penalty: subtract 5 points per defects_reported.
- Refund penalty: subtract 10 points per refund.
- Premium bonus: add 10 points if the product is premium (is_premium is true), else 0.

Intended score:

  score = rating * 20 - 5 * defects_reported - 10 * refunds + (10 if is_premium else 0)

Note: If implementation differs from this spec, tests should capture that difference clearly so we can prioritize a fix later.
