Date: 2026-04-17
Client: Apex Outfitters (DTC outdoor apparel & gear)
Website: https://www.apexoutfitters.com
Platform: Shopify Plus with a custom theme (2019 base, heavily customized)
Stack/Tools: GA4, Klaviyo, TikTok Pixel, Meta Pixel, Intercom chat, Yotpo reviews, Rebuy upsell, Hotjar (occasionally), Cloudflare CDN (basic config)

Attendees:
- Erin Blake (CMO) — primary business sponsor, can approve up to $75k
- David Chen (COO) — final signer for >$75k, strong on ops risk and timelines
- Maya Ortiz (Head of Growth) — internal champion, analytical and proactive
- Notes taken by: Our team

Business context:
- Revenue: ~$25M/year
- Team: ~120 employees
- Traffic: ~250k sessions/month (58% mobile, 42% desktop)
- AOV: ~$180
- Current overall CVR: 0.8% (mobile 0.6%, desktop 1.1%)
- Paid media spend: ~$250k/month

Pain points (verbatim highlights):
- “Mobile is slow; our Largest Contentful Paint is all over the place.”
- “Bounce rate spikes on product pages when we run promos.”
- “We layered on apps over time — now JS is bloated and hard to manage.”
- “We need performance up and conversion up before peak fall season.”

Current performance (mobile, sampled from GA4 + internal tests):
- TTFB: ~900ms
- FCP: ~2.8s
- LCP: ~4.6s
- CLS: ~0.18
- INP: ~280ms
- TBT: ~650ms
- Page weight: ~3.8MB
- Requests: ~142
- Compressed JS: ~780KB
- Images: ~1.9MB
- Third-party scripts: 22 (many load on initial paint)

Impact of issues:
- On mobile, promo traffic bounces early when hero image is slow to display.
- Paid spend inefficiency: estimate 10% of $250k/month wasted due to speed-related bounces (~$25k/mo).
- Internal dev bandwidth constrained; theme updates risky; no performance budget enforced.

Previous attempts:
- Installed image compression plugin; helped a bit but not systematic.
- Removed 2 low-value apps; minimal impact.
- Agency last year focused on SEO content but didn’t touch render path/JS.

Goals (stated):
- Core Web Vitals (mobile): LCP < 2.5s, FCP < 1.8s, INP < 200ms, CLS < 0.1.
- Lift overall CVR from 0.8% to 1.1% (mid) and 1.3% (stretch) within 3 months of launch.
- Maintain SEO equity and brand UX quality.
- Establish a performance budget and quarterly third‑party script review.

Business value framing:
- Baseline monthly revenue ≈ 250,000 sessions × 0.8% × $180 ≈ $360,000.
- At 1.1% CVR: ≈ $495,000/mo → +$135,000/mo.
- 12‑month uplift at 1.1% ≈ $1.62M; CFO applies 40% attribution = ~$648,000 expected value (EV) tied to this initiative.
- At 1.3%, uplift higher; they will still budget using the $648k EV.

Budget & pricing:
- Stated budget comfort: $60k–$100k.
- Could stretch to $125k if ROI is clear (3×+ within 12 months).
- Preference for outcome‑based pricing, not hourly.

Timeline:
- Desire kickoff week of May 12, 2026.
- Pilot fixes and first CRO tests live by June 10, 2026.
- Broad go‑live by July 1, 2026.
- Blackout in November for BFCM — no major deploys then.

Decision process:
- We send proposal by Monday (2026‑04‑20).
- Internal review Tuesday/Wednesday with COO & CFO.
- Vendor decision by Friday (2026‑04‑24).
- Procurement + legal by early May; net 15 terms fine.
- Payment schedule acceptable: 50% on signing, 25% after pilot, 25% on launch.

Stakeholders:
- Erin Blake (CMO) — cares about revenue uplift and brand consistency. Communication style: expressive/driver hybrid.
- David Chen (COO) — cares about operational risk, timelines, and clean rollout. Communication style: analytical/driver.
- Maya Ortiz (Head of Growth) — cross‑functional glue; will push internally. Communication style: analytical.

Constraints/Risks:
- Legal wants cookie consent changes reviewed.
- Theme code brittle; risk of regressions.
- Third‑party apps embedded throughout templates.
- Avoid SEO regressions (structured data, render timing).
- November code freeze.

Competitors:
- Local dev shop: $50k “performance tune‑up” (light CRO, long backlog).
- Specialized performance consultancy: $140k all‑in but 6‑month timeline (too slow for them).

Success criteria (draft):
- Mobile LCP < 2.5s; CLS < 0.1; INP < 200ms.
- CVR increase to ≥1.1% within 90 days of launch.
- Establish and enforce performance budgets (JS ≤ 350KB compressed on mobile routes; images ≤ 800KB total above‑fold).
- Paid media efficiency: reduce bounce on product pages by 10–15% during promos.

Payment/terms noted:
- Comfortable with 50/25/25 milestones.
- Net 15 preferred; can do ACH.

Notes on collaboration:
- They can dedicate Maya (Growth), one in‑house front‑end dev ~10 hours/week, and analytics manager ~5 hours/week for tagging and QA.
- Expect clear weekly status, risk log, and a shared testing plan.