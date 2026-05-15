Project working title: Apex Outfitters — Web Performance Overhaul & Conversion Uplift
Prepared: 2026-04-18

Objective:
- Improve Core Web Vitals on mobile and desktop to industry “good” thresholds.
- Increase overall conversion rate from 0.8% to 1.1% (mid) and 1.3% (stretch) within 90 days of launch.
- Reduce wasted paid media by lowering bounce on key routes (product pages, collections) during promotions.

Outcome targets (mobile-focused, but apply across key routes):
- LCP < 2.5s (target), < 2.3s (stretch)
- FCP < 1.8s
- INP < 200ms
- CLS < 0.10
- JS budget ≤ 350KB compressed on core commerce routes (mobile)
- Above-the-fold image payload ≤ 800KB, hero ≤ 150KB in modern formats (WebP/AVIF)
- CVR uplift to 1.1% within 90 days; stretch 1.3%

Hypothesized levers:
- Critical rendering path: inline critical CSS, defer non-critical CSS/JS, preload LCP image and key fonts.
- Third-party controls: facade/delay non-essential scripts, load on interaction or idle.
- Theme refactor: modularize layout, remove unused CSS/JS, code split where applicable.
- Image pipeline: responsive srcset, modern formats, proper dimensions, fetchpriority on hero.
- CRO foundations: instrument baseline funnel, A/B test quick wins (e.g., add-to-cart button hierarchy, PDP image gallery loading, checkout step hints).
- Performance budget: define, enforce, and operationalize budgets.

Deliverables by phase:
1) Audit & Plan (Weeks 1–2)
- Full performance audit (Core Web Vitals, page weight, requests).
- Third-party script inventory and impact scoring.
- Prioritized fix backlog with effort/impact matrix.
- CRO opportunity map with 3–5 high-probability tests.
- Analytics/measurement plan (GA4 tagging plan, events, and dashboards).

2) Build & Optimize (Weeks 3–6)
- Critical CSS inlining for top templates; defer non-critical CSS.
- Defer/async JS; split bundles; remove unused libraries.
- LCP hero optimization (preload + responsive + modern format).
- Third-party mitigation (facade, load-on-interaction, idle).
- Font strategy (WOFF2 + preload + display rules).
- Implement performance budgets in CI checks where possible.

3) Experimentation & Hardening (Weeks 5–10)
- Launch first two CRO A/B tests (PDP and collection page variants).
- Iterate based on early data; queue next 2–3 tests.
- QA and regression testing (functional + SEO).
- Documentation: before/after metrics, decision log.

4) Launch & Enablement (Weeks 11–12)
- Broad go-live of performance improvements.
- Handoff documentation and playbooks.
- Training session for theme updates without regressions.
- Post-launch monitoring plan (30/60/90-day checkpoints).

Ongoing (tier-dependent)
- 30 to 90 days of support & optimization.
- Quarterly third-party audit template and review cadence.
- Continued A/B testing roadmap and experiment ops.

Client responsibilities:
- Provide access to Shopify, GA4, Cloudflare, and key apps within 3 business days of signing.
- Assign a point person (Maya) and a front-end developer (~10 hours/week) for review and QA.
- Approve/decline A/B test variants within 2 business days of submission.
- Coordinate legal review for consent banner changes within the planned window.
- Join weekly status and decision calls (30 minutes).

Exclusions (explicitly not included unless added via change control):
- Replatforming off Shopify, headless rebuilds, or app rewrites.
- Net new back-end features unrelated to performance/CRO.
- Multi-language or multi-currency implementations.
- Content redesigns beyond agreed CRO variants.
- Any work during November BFCM blackout beyond emergency fixes.

Commercial framing (draft for internal alignment):
- Expected value (12 months, conservative): ~$648,000 (40% attribution on modeled uplift).
- Pricing will use outcome-based tiers tied to value (10–20% of expected value), presented as three options.
- Payment schedule likely 50% on signing, 25% on pilot milestone, 25% at launch.

Proposed timeline (targeting kickoff week of May 12, 2026):
- Week 1–2: Audit complete, plan approved.
- Week 3–6: Implementation of high-impact fixes (pilot live by June 10).
- Week 5–10: A/B tests live, iteration cycles.
- Week 11–12: Broad launch by July 1, training and handoff.
- 30/60/90: Monitoring and optimization (per selected tier).