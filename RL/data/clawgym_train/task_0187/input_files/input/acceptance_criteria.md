# Binance Spot WebSocket Listener — Acceptance Criteria

Objective:
- Capture public Binance Spot trade events using raw WebSocket subscriptions via `uxc subscribe`.
- Write newline-delimited JSON (.jsonl) into output/ paths only.
- Stop after required message counts are met and write a summary.

Streams and Targets:
- Raw stream (single):
  - Endpoint: wss://stream.binance.com:443/ws/btcusdt@trade
  - Transport: websocket
  - Sink: output/raw_btcusdt_trade.jsonl
  - Minimum messages: 15 total data messages
  - Symbol: BTCUSDT
- Combined stream (multi):
  - Endpoint: wss://stream.binance.com:443/stream?streams=ethusdt@trade/bnbusdt@trade
  - Transport: websocket
  - Sink: output/combined_eth_bnb_trade.jsonl
  - Minimum messages: at least 20 total data messages combined
  - Per-stream minimum: at least 10 data messages for each of ethusdt@trade and bnbusdt@trade
  - Symbols: ETHUSDT, BNBUSDT

Formatting and Validity:
- Write only under the output/ directory.
- Each line in .jsonl files must be a single valid JSON object.
- Do not include blank lines or trailing commas in any JSON.
- Use lowercase stream names in all WebSocket endpoints.

Message Shapes and Counting Rules:
- Count only lines that represent market data.
- Raw stream (btcusdt@trade):
  - Accept either:
    - Direct payload with trade fields at the top level (e.g., {"e":"trade","s":"BTCUSDT","t":..., "p":"...", "q":"..."}), OR
    - An envelope with a top-level "data" field that contains the trade payload (e.g., {"data":{"e":"trade","s":"BTCUSDT",...}, ...}).
  - Ignore non-data lifecycle messages like "open" or "closed" if present.
  - At least 5 of the counted messages must include (at the top level or within "data") both e == "trade" and s == "BTCUSDT".
- Combined stream (ethusdt@trade and bnbusdt@trade):
  - Accept either:
    - Top-level combined wrapper with "stream" equal to "ethusdt@trade" or "bnbusdt@trade" and a nested "data" payload (e.g., {"stream":"ethusdt@trade","data":{"e":"trade","s":"ETHUSDT",...}}), OR
    - An outer envelope with a top-level "data" field that itself contains the combined wrapper (e.g., {"data":{"stream":"bnbusdt@trade","data":{"e":"trade","s":"BNBUSDT",...}}, ...}).
  - Within the trade payload, ensure s is "ETHUSDT" for ethusdt@trade and "BNBUSDT" for bnbusdt@trade.
  - Count at least 10 messages for each stream and at least 20 total across both.

Stop Conditions:
- Stop the raw subscription after collecting ≥15 BTCUSDT trade messages.
- Stop the combined subscription after collecting ≥10 ETHUSDT trade messages and ≥10 BNBUSDT trade messages (≥20 total).

Summary File (output/summary.json):
- Must be valid JSON with the following structure:
  {
    "raw": {
      "file": "output/raw_btcusdt_trade.jsonl",
      "count": <number of BTCUSDT trade messages>,
      "symbol": "BTCUSDT"
    },
    "combined": {
      "file": "output/combined_eth_bnb_trade.jsonl",
      "totalCount": <total number of combined trade messages>,
      "countsByStream": {
        "ethusdt@trade": <count for ETHUSDT>,
        "bnbusdt@trade": <count for BNBUSDT>
      },
      "symbols": ["ETHUSUT", "BNBUSDT"]
    }
  }
- Requirements:
  - raw.count >= 15 and raw.symbol == "BTCUSDT".
  - combined.totalCount >= 20.
  - combined.countsByStream.ethusdt@trade >= 10 and bnbusdt@trade >= 10.
  - combined.symbols includes "ETHUSDT" and "BNBUSDT".
  - File paths must match exactly as shown.

Notes and Guardrails:
- Stream names must be lowercase in endpoints.
- Prefer base host wss://stream.binance.com:443.
- Use the raw websocket transport: `--transport websocket`.
- It is acceptable for the sink files to include event envelopes; ensure you only count actual market data messages per the rules above.
- Write only to output/ and avoid absolute paths.

Examples (illustrative only):
- Raw direct payload line:
  {"e":"trade","E":1734020400000,"s":"BTCUSDT","t":123456789,"p":"43210.12","q":"0.005","b":111,"a":222,"T":1734020400001,"m":false,"M":true}
- Combined wrapper line:
  {"stream":"ethusdt@trade","data":{"e":"trade","E":1734020401000,"s":"ETHUSDT","t":987654321,"p":"2350.55","q":"0.10","b":333,"a":444,"T":1734020401001,"m":true,"M":true}}

Acceptance will fail if:
- Any required output file is missing.
- Any .jsonl line is invalid JSON.
- Counts or symbols do not meet the minimum thresholds.
- summary.json is missing keys or contains incorrect paths or values.