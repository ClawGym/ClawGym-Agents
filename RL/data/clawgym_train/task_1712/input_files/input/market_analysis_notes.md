# Market Gap Analysis — Home Office Seating
Date: 2026-04-17

## Context
We analyzed the "desk chairs" segment across Amazon and Shopify stores to find underserved gaps. Data sources included competitor listings, top 500 reviews, and search terms.

## User Corrections
- Package manager: This repo uses pnpm workspaces. Stop suggesting `npm install`; use `pnpm install`. CI failed due to lockfile mismatch (pnpm-lock.yaml).
- Taxonomy: Split "desk chairs" into two distinct subcategories — ergonomic chairs vs gaming chairs — for clearer gap mapping and pricing benchmarks.

## Findings (Highlights)
- Competitor blind spot: Few options with adjustable lumbar + breathable mesh under $200 (ergonomic).
- Review pain points: Wobble after 3 months, armrests scraping desks, and unclear max height range.
- Search demand vs supply: Rising queries for "no-screw assembly chairs", limited coverage.

## Workflow Notes
- When scraping and clustering review themes, we manually grouped issues (time-consuming).
- We prepared a comparison table but stakeholders asked for a CSV export for their BI tool.

## Feature Requests
1) Auto-cluster review pain points into themes (e.g., build quality, ergonomics, assembly) and output a gap summary per subcategory.
2) Export the gap table (with competitor coverage matrix) to CSV and JSON for stakeholders to download.
3) Optional: A “Compare to Competitor X” quick chart generator that highlights missing features at given price points.

## Operational Conventions to Confirm
- Monitoring: For production-critical domains, set SSL warn-days to 21 so alerts land a week before sprint planning. Non-critical: 14 is ok.
- Batch checks: Prefer a single multi-domain SSL check with `--json` for consistent CI gating.

## Next Steps
- Update taxonomy in templates.
- Implement auto-clustering + export.
- Document the pnpm requirement in CLAUDE.md and AGENTS.md.

Related files:
- input/ssl_results.json
- input/events.jsonl