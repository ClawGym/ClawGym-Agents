Order totals utility for a small e-commerce operation.

Context:
- The business was based in Melbourne (VIC) and recently moved to Adelaide (SA).
- The current script (scripts/process_orders.py) uses a hardcoded 8% surcharge that was fine for VIC but doesn’t adapt by state.
- Goal: Make surcharge state-aware using data/shipping_rates.json and rely on config/app.json for runtime settings.
- We’ll review this with our bookkeeper in SA after the refactor to ensure it aligns with our internal processes.
