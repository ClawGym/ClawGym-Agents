Strategy Brief: Hybrid Value + Momentum (V1)

Goal
- Build a hybrid value + momentum stock selection screen that favors fundamentally solid, reasonably priced companies with positive recent price strength.
- Target a medium concentration output (top 30 names).
- Typical holding period: 4–8 weeks; re-evaluate weekly.

Universe and Exclusions
- Focus on liquid, tradeable stocks with available fundamentals and daily data.
- Avoid penny stocks and extremely illiquid names.

Fundamental (Value) Filters — required
- pe_ttm: prefer reasonably priced companies; avoid negatives or extremes.
  • Use bounds: 5 <= pe_ttm < 30
- pb: avoid overvalued balance sheets.
  • Use bound: pb < 4
- roe: quality tilt.
  • Use bound: roe >= 0.10 (10%)
- netprofitmargin: profitability screen.
  • Use bound: netprofitmargin >= 0.05 (5%)

Daily Liquidity/Technical Filters — choose at least two
- Minimum price filter: close >= 3
- Liquidity threshold: 20-day average volume >= 500,000 shares (ma(volume, 20) >= 500000)
- Trend confirmation: close > ma(close, 50)

Factors
- Inline factors (must include and name exactly as below):
  • momentum_20d: (close / delay(close, 20)) - 1, direction: positive
  • ma10_deviation: (close - ma(close, 10)) / ma(close, 10), direction: negative
- External factors (select exactly two from the provided catalog):
  • Preferred: alpha101/alpha_008 (capital flow/accumulation themed)
  • Preferred: alpha101/alpha_029 (short-to-intermediate-term momentum themed)

Weighting Guidance
- Normalize with zscore.
- Assign weights to all four factors summing to 1.0.
- Suggested weights:
  • momentum_20d: 0.35
  • ma10_deviation: 0.15
  • alpha101/alpha_008: 0.25
  • alpha101/alpha_029: 0.25

Output
- Limit: 30 names.
- Include columns: symbol, name, score, roe, pe_ttm, momentum_20d, ma10_deviation, and both external factor identifiers used.

Notes
- The value screens should meaningfully narrow the universe without being overly restrictive; adjust pe_ttm/pb bounds conservatively as above.
- Liquidity/price filters are intended to avoid microstructure noise and impractical candidates.
- Factor directions: momentum_20d positive (higher is better), ma10_deviation negative (lower deviation favored to avoid overextended entries).
- If the screen returns too few results, consider relaxing pb to < 5 or pe_ttm upper bound to < 35; if too many, tighten pb to < 3.5 or increase minimum price to close >= 5.