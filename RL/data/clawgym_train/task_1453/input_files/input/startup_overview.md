# ParcelLoop — Company Overview

Company: ParcelLoop, Inc.  
Founded: 2024  
HQ: Austin, TX (remote-first)  
Team size: 28 (as of 2026-03-31)  
Focus: Logistics SaaS for parcel shipping orchestration and optimization

Summary
ParcelLoop provides a multi-carrier shipping platform for SMB and mid-market e-commerce and light 3PLs. The product unifies rate-shopping, label generation, tracking/alerts, returns portals, and predictive delivery ETAs across USPS, UPS, FedEx, DHL eCommerce, and regional carriers. Integrates with Shopify, WooCommerce, BigCommerce, NetSuite, and popular WMS tools.

Founding Team
- Alex Chen (CEO): Former Group PM at Shippo; led carrier pricing optimization and merchant analytics.
- Priya Nair (CTO): Former Senior Staff Engineer at Stripe; built low-latency, high-availability infra and observability systems.
- Miguel Ortega (COO): 10+ years at FedEx Ground operations; last role: Regional Ops Planning Manager.

Advisors: Former VP Logistics at a top 3PL; ex-UPS enterprise sales director.

Product
- Core modules: Multi-carrier rate-shopping and label generation, tracking and customer notifications, returns workflow, address validation, carrier performance analytics.
- API-first: REST + webhooks; SDKs for Node and Python; average label creation latency < 200 ms.
- Integrations: Shopify, WooCommerce, BigCommerce, NetSuite, Skubana, Cin7, 3PL Central.
- Reliability: 99.3% uptime over the last 90 days (see metrics.tsv).
- Security: SOC 2 Type I completed (Dec 2025); Type II in progress (target Q3 2026). GDPR DPA and SCCs available; SSO for Business tier.

Pricing and Monetization
- Tiered SaaS: $99, $299, $799 per month by volume/features.
- Usage: $0.03 per label beyond tier limits; discounted rates for 3PLs.
- Revenue mix: Recurring subscription plus usage. Recurring revenue historically ~88% of total (see metrics.tsv).

Go-To-Market
- Self-serve onboarding for SMBs; assisted onboarding for 3PLs and mid-market D2C brands.
- Sales: Inbound-led with SDR support for 3PL and multi-brand accounts; current sales cycle ~46 days (metrics.tsv).
- ICPs: (1) 3PLs consolidating dozens of micro-merchants under one umbrella, (2) D2C brands shipping 5k–50k parcels/month, (3) marketplaces with multi-node fulfillment.

Traction (as of 2026-03-31)
- 569 paying accounts; MRR ~$182k (metrics.tsv; financials.csv).
- ARPU: ~$320/month; Blended CAC: ~$3,500; 12-month NDR ~118% (metrics.tsv).
- Top 10 accounts ~53% of MRR; top 2 accounts ~28% (customers.jsonl; metrics.tsv).
- Notable customers: FitBox Co (3PL), NorthPeak Apparel, GlowSkin Beauty (customers.jsonl).

Market and TAM
- Target: SMB/mid-market e-commerce and light 3PL parcel shipping orchestration.
- US SMB e-commerce merchants with >1,000 shipments/month: ~180,000 (internal estimate from public merchant and marketplace data).
- Estimated annual spend on shipping software and related tools: $800–$2,400 per merchant; mid-market/3PL up to $50k+ per year.
- TAM approach: (a) SMB/mid-market SaaS TAM: ~180k merchants × avg $1,500 = $2700M; (b) 3PL/logistics platforms: incremental ~$300–500M in software spend → blended TAM ~$3.0–3.2B globally, with US/EU comprising ~70%. ParcelLoop focuses initially on US SMB/mid-market → serviceable obtainable market (SOM) estimate ~$400–600M over 5 years through direct SaaS and usage-based fees.

Why Now
- Carrier and surcharge complexity has increased (peak, DIM, fuel, zone-based shifts), making dynamic rate-shopping and rules-based carrier selection more valuable.
- USPS Ground Advantage and ongoing regional carrier expansion introduce meaningful savings opportunities if orchestrated correctly.
- Returns continue to rise; standardized returns experiences are now a requirement for conversion.
- Compliance tightening (e.g., EU ICS2 final phases) increases the value of accurate data and automation.

Competitive Landscape
- Shipping APIs / orchestration: Shippo, EasyPost, ShipEngine.
- SMB shipping platforms: ShipStation, Pirate Ship.
- Enterprise visibility/orchestration: project44, Flexport (more freight-focused).
- Differentiation: ParcelLoop aims to bridge ease-of-use (SMB UI/UX) with robust multi-carrier optimization and analytics typically found in mid-market tools. Data-driven rate recommendations, predictive ETAs, and a returns workflow integrated with support tooling are key focus areas.

Defensibility Levers
- Integration depth with multiple carriers and WMS/commerce platforms (switching cost).
- Data network: growing normalized dataset of parcel lanes, surcharges, and delivery performance to power rate and SLA recommendations.
- Workflow embeddings: Returns portals, CS tools, and ERP/WMS integrations reduce rip-and-replace likelihood.

Operational Notes and Risks
- Uptime 99.3% over last 90 days; one notable January incident with elevated error rates (customers.jsonl references).
- Concentration risk: Top accounts represent ~28% of MRR (customers.jsonl).
- SOC 2 Type II pending; enterprise deals may require completion (metrics.tsv and this document).

Use of Funds (proposed for Seed)
- Complete SOC 2 Type II and strengthen SRE function.
- Broaden regional carrier integrations; deepen 3PL features.
- Expand sales coverage and partner channels (ERPs and 3PLs).
- Working capital to reduce downtime risk and accelerate analytics roadmap.

Data sources
- financials.csv: monthly revenue, COGS, operating expenses, and cash balances.
- metrics.tsv: ARPU, churn, gross margin, MRR, CAC, NDR, uptime.
- customers.jsonl: customer interviews and concentration indicators.
- cap_table.json: current ownership and option pool status.

Assumptions
- TAM inputs derived from public merchant counts and typical software spend; intended as directional and conservative.
- All financial and operating metrics tie to the supplied files; no external adjustments included here.

---