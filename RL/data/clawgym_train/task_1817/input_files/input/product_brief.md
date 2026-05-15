# Product Brief — SafeKitchen AI

Product: SafeKitchen AI  
Tagline: AI-powered food safety compliance logging for independent restaurants (HACCP logs, temperature checks, automated reminders, and inspection-ready reporting) — United States

## What it is
SafeKitchen AI replaces paper-based or ad-hoc digital logs with:
- Digital HACCP logs and smart temperature check workflows
- Automated reminders, shift-level task schedules, and escalation
- Health-inspection-ready reporting and audit trails
- Optional integrations: Bluetooth temperature probes and cloud POS (for timestamps, staff accountability)
- AI prompts to nudge compliance before inspections (e.g., “You missed the 2 pm cook-cool temp check on Grill Station”)

## Who buys it
- Primary buyer: Independent restaurant owner-operator, General Manager, or Kitchen Manager
- ICP: Single-location and small groups (1–5 units), Full-Service Restaurants (FSR) and Quick-Service Restaurants (QSR)
- Not targeting national chains in initial phase

## Business model and revenue unit
- Model: B2B-SaaS (per-location subscription); hardware optional and separate
- Geography: United States-only for the first 24 months; focus metros: CA, TX, FL, NY, IL, GA, WA, CO
- The revenue unit is a per-location annual SaaS subscription sold to independent restaurants at an estimated $1,080/year (blended ACV).

## ACV derivation (competitor + value-based)
- Competitor pricing anchor (see competitor_pricing.csv):
  - Range observed: ~$65–$120 per location per month
  - Median cluster: ~$79–$99 per location per month
  - Annualized median: ~$90/month × 12 = $1,080/year
- Value-created check (independent unit economics):
  - Labor time saved from digital logs + reminders: 20–30 min/day of supervisor time
    - 25 min/day × 365 days ≈ 152 hours/year
    - Weighted wage (with burden) ≈ $18–$22/hour → $2,700–$3,350/year
  - Avoided spoilage from tighter temp control: 0.5–1.5% of food cost
    - Typical independent food cost ≈ $180k–$240k/year → $900–$3,600/year (use $1,500 midpoint)
  - Fewer fines/reinspection fees: amortized $300–$800/year
  - Total economic value: ≈ $4,500–$7,600/year
  - Value-based pricing at 12–18% of value → $540–$1,370/year → aligns with $1,080/year anchor
- Segment ACVs used for planning:
  - QSR: $900/year per location (lean staffing; simpler line checks)
  - FSR: $1,300/year per location (more stations/processes; higher reporting complexity)
  - Blended ACV (mix below): ≈ $1,084/year

## NAICS, firm counts, and independence mix (for bottom-up)
- Primary NAICS in scope:
  - 722511 — Full-Service Restaurants
  - 722513 — Limited-Service (Quick-Service) Restaurants
  - Excluded from core scope: 722410 (Drinking places), 722514 (Cafeterias), 722515 (Snack/Nonalcoholic Beverage Bars)
- Establishment counts (US, latest CBP/Economic Census window):
  - 722511 (FSR): ~294,000 establishments
  - 722513 (QSR): ~298,000 establishments
  - Total relevant (FSR + QSR): ~592,000 establishments
  - Source basis: US Census Bureau County Business Patterns (CBP) 2022; NAICS 7225xx tables
- Independent vs. chain mix:
  - Independent single-unit share of restaurant locations: ≈ 50–56% range; use 53% midpoint
  - Independent relevant universe: 592,000 × 53% ≈ 313,000 independent locations
  - Independent segment mix (share of independent locations):
    - QSR: 54% → ~169,000 locations
    - FSR: 46% → ~144,000 locations
  - Blended ACV check:
    - 0.54 × $900 + 0.46 × $1,300 = $486 + $598 = $1,084/year

## Adoption and SAM filter anchors
- Tech readiness (cloud/mobile workflow adoption among independents): ~65–75% (use 70% midpoint)
  - Basis: National Restaurant Association (State of Restaurant Technology 2024), Toast Restaurant Technology Report 2023
- Willingness/ability to pay for food safety tooling (among tech-ready independents): ~50–70% (use 60% midpoint)
  - Basis: POS/restaurant tech adoption surveys (Toast/Upserve 2023–2024), NRA cost-control benchmarks
- Operational fit (exclude micro-concepts with no hot line/limited food handling): 5–15% reduction (use 10%)
  - Basis: concept mix and food-prep complexity analysis; snack/beverage-only shops excluded by NAICS selection above
- Example SAM math scaffold (you can recompute precisely in the report):
  - Starting pool: ~313,000 independent FSR+QSR locations
  - × Tech-ready (70%): ~219,100
  - × Willingness to pay (60%): ~131,460
  - × Operational fit (retain 90%): ~118,314 locations
  - Revenue using blended ACV $1,084: ≈ 118,314 × $1,084 ≈ $128M (range depends on filters and ACV ±)

## Top-down category anchors (for cross-checks)
- Restaurant Management Software (RMS), global market:
  - Grand View Research (2024): ~$6.9–$7.5B (global), ~10–15% CAGR
  - Assume US share ~30–40% → US RMS: ~$2.1–$3.0B
  - Food safety/compliance share within RMS: ~10–15% → ~$210–$450M US
- Food Safety Software (cross-vertical), global:
  - Mordor Intelligence / IMARC / Precedence (2023–2025 range): ~$0.8–$1.1B (global)
  - Assume US share ~28–35% → US: ~$225–$385M
  - Restaurant/foodservice share of category: ~35–45% → US restaurant food safety software: ~$80–$170M
- Independent share of locations/spend: ~50–56% of units; share of software spend ~50–60% (spend skewed to chains)
  - Useful as a funnel step for independent-only TAM/SAM

Note: Use two sources minimum in the top-down method and reconcile scope differences (RMS vs. food safety point-solutions vs. cross-vertical food safety).

## Summary anchors you can use
- Independent FSR+QSR locations (US): ~313k
- Segment mix (independents): QSR 54%, FSR 46%
- ACVs: QSR $900/yr; FSR $1,300/yr; Blended ≈ $1,084/yr
- Filters: Tech-ready 70%; Willingness to pay 60%; Operational fit retain 90%
- Top-down US category (food safety in RMS): ~$210–$450M; cross-vertical food safety software (restaurant slice): ~$80–$170M

## Citations and references (for your Sources section)
- US Census Bureau, County Business Patterns (CBP) 2022 — NAICS 722511 and 722513 establishment counts
- National Restaurant Association (State of Restaurant Technology 2024) — cloud/mobile adoption indicators
- Toast Restaurant Technology Report (2023) — independent tech adoption and willingness to pay sentiment
- Grand View Research (Restaurant Management Software Market, 2024 update) — global RMS size and NA share
- Mordor Intelligence / IMARC / Precedence Research (Food Safety Software, 2023–2025) — global category size and regional shares
- Technomic (2023) — independent vs. chain location share benchmarks

Assumptions are documented where precise public figures vary by source. Use conservative midpoints and show ranges.

---

Operational note: Hardware (sensors/probes) are optional add-ons and not included in the software ACV unless explicitly stated. For consistency with competitor medians, assume software-only ACV for TAM/SAM/SOM; call out if hardware is required for certain features.