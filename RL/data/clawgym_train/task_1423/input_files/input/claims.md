# Quick fact-check of supplier deck – pipe offers

Please verify the following statements using input/offers.csv:

1. The average unit price for 600 mm PN16 pipes across all suppliers is at most 245 USD per meter.
2. For 1000 mm PN16 pipes, the minimum quoted unit price is below 400 USD per meter.
3. No offers have a lead time longer than 100 days.
4. All PN10 offers are compliant (compliance_flag = 'Y').
5. Across all offers, the overall average unit price is below 300 USD per meter.

Notes:
- "PN10" corresponds to pressure_class_bar = 10 and "PN16" corresponds to pressure_class_bar = 16.
- Unit prices are in USD per meter; lead times are in calendar days.
