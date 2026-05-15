# Expense Reporting Policy (FX)

- Reporting currency: EUR.
- Official rate source: European Central Bank (ECB) Euro foreign exchange reference rates (EXR).
- Conversion rule by transaction date:
  - If a transaction’s date has a published ECB rate, use that day’s rate.
  - If the date has no rate (weekend/holiday), use the most recent preceding business day with a rate.
- For EUR transactions, use a rate_to_eur of 1.0.
- Round final converted_amount_eur to two decimal places.
- Maintain an audit trail including: the rate file used, basic file inspection commands and outputs, and a count of processed vs. excluded transactions.
