Q4 Sales Insights Brief (North, South, West)

Timeframe
- Period: Q4 2025 (October 1, 2025 – December 31, 2025)
- Regions in scope: North, South, West
- Data sources:
  - input/north.csv
  - input/south.csv
  - input/west.csv

Objectives
- Produce regional Q4 insights for North, South, and West with consistent structure.
- Compare monthly trends within Q4 (Oct, Nov, Dec) and highlight notable shifts.
- Identify region-specific risks and bottlenecks (e.g., stockouts, high return rates).
- Recommend actions per region and at the consolidated level.

Primary KPIs (calculate for each region and month, plus Q4 totals/averages)
- Revenue (sum of monthly revenue)
- Orders (sum of monthly orders)
- Average Order Value (AOV = revenue / orders; accept rounding to 2 decimals)
- Return rate = returns_value / revenue
- Discount rate = discounts / revenue
- ROAS = revenue / marketing_spend
- New customer mix = new_customers / orders
- Repeat order share = repeat_orders / orders
- Stockouts (sum of monthly stockouts)

Expectations for Regional Analyses
- Use the standardized section order:
  1) Summary
  2) Key Metrics
  3) Risks
  4) Recommendations
  5) Data Sources
- Cite the exact data source path in “Data Sources”.
- Keep region names standardized as: North, South, West.
- Focus on month-over-month patterns across October, November, December.
- Quantify KPI highlights and call out thresholds:
  - Return rate > 6% should be flagged as a risk.
  - ROAS target: ≥ 4 is healthy; 3–4 needs attention; < 3 is a concern.
  - Discount rate > 8% merits scrutiny for margin pressure.
  - Persistent stockouts (double digits per month) indicate supply constraints.

QA Review Guidance
- Verify that AOV is consistent with revenue and orders within a 1% tolerance; if not, flag and comment.
- Check region naming is consistent (North, South, West only).
- Confirm all three months (2025-10, 2025-11, 2025-12) are present for each region.
- Compare cross-region KPIs and flag outliers (e.g., unusually high return rate or low ROAS).
- Note any data gaps or anomalies and propose how to interpret them.

Synthesis Requirements (Final Consolidated Report)
- Synthesis Mode: consolidate
- Sections to include:
  - Executive Summary
  - Comparative Analysis
  - Unified KPIs
  - Recommendations
  - Appendix: Methodology
- Integrate and reconcile QA observations before finalizing.
- Reference all three regions (North, South, West) explicitly.
- Keep all paths relative (e.g., input/... and output/...).

Notes
- Stockouts indicate count of stockout events (operational signal).
- Minor rounding differences are acceptable; document any material discrepancies.
- Do not import external data; base all findings on the provided CSVs.