Project: Local-only Multi-Timeframe Technical Analysis

Data sources:
- Use only the CSVs under input/ohlcv/ (no network calls).
- Column order for all CSVs: timestamp,open,high,low,close,volume (last row is most recent).
- All prices and volumes are numeric values.

Symbols & Timeframes:
- BTC/USDT (1h)
- BTC/USDT (4h)
- ETH/USDT (4h)

Output files to produce:
1) Per slice JSON (machine-readable):
   - Path: output/analysis/{SYMBOL_NO_SLASH}_{TIMEFRAME}.json
   - Required:
     • symbol (string, e.g., "BTC/USDT")
     • timeframe (string, e.g., "1h")
     • current_price (number; last close)
     • indicators (object) with:
       - rsi (number or null)
       - macd (object: macd, signal, histogram; numbers or nulls)
       - bollinger (upper, middle, lower; numbers or nulls)
       - atr (number or null)
       - adx (number or null)
       - mfi OR williamsR (at least one number or null)
       - pivotPoints (pp, r1, r2, r3, s1, s2, s3; numbers or nulls)
       - fibonacci (level0, level236, level382, level500, level618, level786, level100; numbers or nulls)
       - keltner (upper, middle, lower; numbers or nulls)
       - donchian (upper, middle, lower; numbers or nulls)
       - vwap (number or null)
       - ichimoku (tenkan, kijun, senkouA, senkouB; numbers or nulls)
       - supertrend (trend in {"bullish","bearish","neutral"}; upper, lower numbers or nulls)
       - support_resistance (support[] and resistance[] numeric arrays; nearestSupport, nearestResistance numbers or nulls)
     • patterns (array of objects with: type, direction) — may be empty
     • volume_analysis (string)
     • recommendation (object):
       - action in {"buy","sell","hold"}
       - confidence (integer 0–100)
       - stop_loss (number)
       - take_profit (number)
       - rrr (number; risk-reward ratio)
       - rationale (string)
     • timestamp (string; ISO-like or "N/A")

   - Trade levels:
     • For long idea: stop_loss ≈ current_price - 1×ATR, take_profit at nearest resistance or ≈ current_price + 2×ATR
     • For short idea: invert accordingly
     • For hold/neutral: still compute levels and explain why.

   - All numeric fields must be actual numbers (not strings). JSON must be valid.

2) Cross-instrument summary:
   - output/summary.md must include:
     • Clear sections labeled exactly: "BTC/USDT (1h)", "BTC/USDT (4h)", "ETH/USDT (4h)"
     • A brief per-market synopsis with directional bias, indicator highlights, notable patterns (if any), and top 3 support/resistance levels used
     • At least one line containing either "Indicators used:" or "Patterns detected:"
     • A short explanation of ATR-based stop loss and take profit construction
     • A section titled "Risk Disclaimer" that includes the sentence: "This is not financial advice."

3) Watchlist CSV:
   - Path: output/watchlist.csv
   - Header must be exactly:
     symbol,timeframe,bias,action,stop_loss,take_profit,nearest_support,nearest_resistance
   - One row per analyzed slice
   - bias in {bullish,bearish,neutral}; action matches JSON
   - Numeric columns must contain numbers.

Constraints:
- No external services/APIs allowed.
- If an indicator is not computable due to insufficient data (e.g., Ichimoku lead spans), include the field with null values and note this in summary.md.
- Maintain consistency across JSON, CSV, and summary narratives.
- Create output directories as needed.