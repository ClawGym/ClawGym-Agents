Equity Strategy Draft — Earnings Day Intraday Breakout (Rough Notes)

Working hypothesis (rough):
- On earnings announcement days, highly liquid, large-cap U.S. stocks that gap up at least ~2% and show strong early volume tend to continue higher if they break above the first 30-minute high, providing a short-term continuation edge into the same-day close (and occasionally the next morning).

Motivation and observations:
- I’ve noticed that on clean beats with positive guides, large names open strong and keep pressing after taking out the early range.
- Early volume spike matters: breakouts with >2x the 20-day average volume in the opening half hour seem to have fewer fake-outs.
- I’ve been inconsistent with timing (sometimes entering right at 9:45, other times waiting for a retest). Need to remove discretion.

Current discretionary rules (to be codified):
- Universe: Prefer U.S. large caps (Russell 1000-ish), price > $5, avg 20D volume > 1.5M shares. Avoid ADRs and ETFs. I sometimes skip small caps even if liquid.
- Event: Same-day earnings (pre-market or after-hours prior day). I only trade names on earnings days.
- Gap condition: Up gap ≥ 2.0% vs prior close. I sometimes accept 1.8% if the name is mega cap and the beat is strong—this is discretionary and should be standardized.
- Volume condition: Opening 30-minute volume ≥ 2.0× 20D average 30-minute volume proxy (I used volume_vs_20d ≥ 2.0 as a crude ratio). I sometimes eyeball time-and-sales—remove this human element.
- Entry trigger (discretionary now): 
  - Breakout above first 30-minute high with a small buffer (I’ve been using “a few cents” or ~0.05%).
  - At times I wait for a retest of the 30-min high; other times I enter on the first break. This must be standardized.
- Order type: I’ve alternated between stop-market and stop-limit with a 2–5 bp limit offset. I assume ~5–10 bps of slippage in practice.
- Sizing: Target ~0.5% of equity risk per trade based on stop distance. I occasionally reduce size in very high-volatility sessions—this should be explicitly parameterized or removed.
- Exits: Use a profit target around 3% and a stop around 1.5–2.0%, or exit at end of day if neither hits. Sometimes I hold into the next morning if earnings momentum looks exceptional—this is discretionary; likely remove.
- Short side: Mirroring the setup on gap-down days has been less reliable in my notes; I’ve mostly avoided shorts for this pattern. I’m fine with focusing long-only for now.

Execution/cost assumptions (rough):
- Commission: negligible per-share rate at my broker; assume a per-trade minimum to be conservative.
- Slippage: I’ve been assuming ~5–10 bps in liquid large caps, worse during high volatility; quant should test 1.5x–2.0x slippage multipliers.
- Fills: Realistically, worst-case entry at ask + 1 tick and exits at bid - 1 tick happen often on momentum names.

Data and biases:
- Ensure earnings flag is timestamp-aligned (no look-ahead).
- Use survivorship-bias-free universe with delisted names included.
- Include all stocks meeting criteria, not only winners I remember.

What to standardize for the quant:
- Universe: U.S.-listed common stocks, market cap ≥ $10B, price ≥ $5, 20D average volume ≥ 1.5M shares. Exclude ADRs, ETFs, preferreds.
- Event: Confirmed earnings day. Gap ≥ 2.0% up from prior close at official open.
- Volume: Opening 30-minute volume ratio ≥ 2.0× vs 20D average 30-minute volume proxy (or a practical proxy using total 20D average volume if intraday slices aren’t available).
- Entry: At 10:30 ET, place a stop-limit (or stop-market if needed) to buy if price exceeds the first 30-minute high by 0.05% within the trading day. If not triggered by 15:00 ET, cancel.
- Stop/Target/EOD: Initial stop 1.8% below entry, profit target 3.0% above entry, time exit at same-day close if neither hits.
- Position sizing: Fixed fraction risk: 0.5% of equity risked to the initial stop distance per trade; round to nearest 100 shares or use detailed share calc.
- Costs: Use realistic commissions plus conservative slippage; stress test with 1.5x and 2.0x multipliers.
- No discretionary overrides: No skipping because of “feel,” news tone, or tape-reading—must trade all qualifying signals.

Notes from sample trade log (approximate):
- Winners cluster when volume ratio ≥ 2.0 and the gap is clean (no immediate fill of the gap).
- Losers often occur in high-volatility regimes where first 30-minute range is wide and fake-breaks happen.
- Some names (mega caps) handle better than mid caps—this may be captured by the market cap floor.

Questions for the backtest design:
- Should we use stop-market or stop-limit for the trigger? My bias is stop-market for reliability, but model both and include worst-case fills.
- How to handle multiple qualifying tickers on the same day? I’ve typically taken up to 3 names; maybe limit portfolio risk to 1.5% (three positions at 0.5% risk each). Needs explicit rule if portfolio-level cap is desired.
- Consider adding a volatility filter (e.g., skip days where the first 30-minute range is > 3% of price), but start simple and evaluate later.

Pass/fail thinking:
- Strategy should work across bull/bear and high/low volatility regimes with acceptable (not necessarily best) performance.
- Require year-by-year positive expectancy in most years and at least 100–200+ trades overall.
- If results depend on a very specific stop/target or precise timing, it’s probably curve-fitting.

Hand-off goal:
- Produce a fully codified, zero-discretion spec with clear entry time, trigger, order type, exits, sizing, filters, and universe so the quant can implement and run robust stress tests and a walk-forward out-of-sample validation.