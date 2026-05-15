Title: 15-minute BTC/USDT Momentum Trend-Following Futures Bot (Research Desk)

Objective
- Build a bi-directional momentum/trend-following system to capture intraday swings on BTC/USDT perpetuals using 15-minute bars.
- Emphasize disciplined risk control with ATR-based stops and a single-position policy to avoid overexposure.

Scope & Defaults
- Exchange/data: Binance USDT-M (futures), offline local CSV only.
- Symbol: BTC/USDT.
- Timeframe: 15m.
- Test capital: $10,000.
- Leverage baseline: 12x (neutral-aggressive). Cap 20x unless explicitly increased in later experiments.

Directional Bias
- Bi-directional (long in uptrends, short in downtrends). No long-only or short-only constraint.

Entry Logic (signal generated on bar close)
- Trend filter: 200 EMA defines regime (price above = uptrend bias; below = downtrend bias).
- Momentum trigger:
  - Long: 20 EMA crosses above 50 EMA and RSI(14) > 55; confirm ADX(14) > 18.
  - Short: 20 EMA crosses below 50 EMA and RSI(14) < 45; confirm ADX(14) > 18.
- Optional breakout confirmation: close > prior 20-bar high for long; close < prior 20-bar low for short (only when volatility filter is satisfied; see below).
- Volatility/chop filter: Use ATR(14)/price as a normalized volatility proxy. Skip signals when normalized ATR < 0.15% and 20/50 EMAs are nearly flat (absolute slope over last 10 bars < 0.02% per bar).

Exit Logic & Risk Controls
- Initial stop loss: ATR(14)-based hard stop at sl_atr_mult = 2.7 from entry price (wide enough for 12x leverage).
- Take profit: primary target at +1.8R; after hitting +1.0R, trail with a dynamic stop = entry-adjusted 1.0 ATR behind price (long) / above price (short).
- Time-based exit: if trade remains open > 4 days worth of bars (max holding), close on the next bar close.
- Cooldown: minimum 2 bars after any exit before new entries in the same direction.
- Max concurrent positions: 1.
- Position sizing: risk 1.0% of account equity per trade to initial stop (balance updates allowed only between trades, not intra-trade).

Execution & Costs
- Orders: market entries at signal bar close; stop orders for SL; limit or market for TP per backtester conventions.
- Fees: assume 0.06% round-turn.
- Slippage: 0.02% per trade (entry + exit combined).
- Ignore funding for this research pass.

Leverage & Safety Guardrails
- Baseline leverage: 12x.
- Hard cap: 150x (not used here).
- If leverage > 20x in future experiments, enforce sl_atr_mult >= 2.5.
- Backtest cap: <= 365 days.
- No live trading or external uploads in this run.

Weekly Evolution (Enabled)
- Frequency: weekly segments on 15m data.
- Tunable parameters and ranges:
  - sl_atr_mult: 2.4–3.3 (default 2.7).
  - tp_rr: 1.4–2.2 (default 1.8).
  - adx_threshold: 15–25 (default 18).
  - rsi_long/short thresholds: 50–60 / 40–50 (defaults 55/45).
  - ema_fast/ema_slow: 15–30 / 40–70 (defaults 20/50).
  - breakout_lookback: 10–30 (default 20).
  - normalized_atr_floor: 0.10%–0.25% (default 0.15%).
- Reflection heuristics:
  - If false breakouts rise: increase ADX threshold and/or raise breakout_lookback.
  - If stop-outs cluster in chop: raise normalized_atr_floor or widen sl_atr_mult slightly.
  - If exits leave too much on the table in trends: ease the trailing stop a bit (higher ATR multiple) or increase tp_rr modestly.
  - If missed moves in strong trends: lower ADX threshold slightly and/or lower RSI trigger by 2–3 points within bounds.

Reporting
- Provide bilingual bot copy (English + Chinese) for name, personality, and description in the final parameters JSON.
- Document evolution schedule with at least 3 rounds and concise rationales.
- Backtest result should include return, Sharpe, trade count, the evolution log with at least one segment note, and reference the CSV path used.

Operational Constraints
- Use only the provided local CSV (input/BTCUSDT_15m_148d.csv).
- No external network calls, uploads, or live trading in this run.

Quality Notes
- Keep the personality consistent with a disciplined, momentum-seeking trend follower.
- Prefer fewer but higher-quality trades in choppy regimes; be more permissive in clean trends.

Success Criteria
- Coherent parameter set aligned with the brief and guardrails.
- Evolution shows meaningful, bounded adjustments guided by segment reflections.
- Clear execution summary and risk disclosure.