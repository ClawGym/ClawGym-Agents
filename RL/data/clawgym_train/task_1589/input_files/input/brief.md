Project: Onboarding Revamp — team focus is improving first-run experience and activation for new customers.

Why this matters: onboarding is the first impression and is tied directly to retention and expansion. Our Q2 OKRs center on two user-facing outcomes and one engineering outcome:
- Improve new user activation rate from 38% to 55%.
- Reduce p95 latency in the first-run experience to 380ms.
- Decrease time-to-first-value to under 5 minutes for at least 70% of new sign-ups.

Scope highlights: “Guided Setup v2” (wizard + inline help + auto-detection) is the primary feature, plus a supporting performance sprint for API endpoints used during account creation and the quick-start checklist.

Current status:
We soft-launched Guided Setup v2 to 20% of new sign-ups last week (randomized, desktop-first). Early signal: completion rate up ~6 pts in the treatment cell; drop-off concentrates at the data-connection step. We shipped backend caching for the capabilities endpoint and removed a blocking third-party call. Latest performance figures from Saturday’s run: first-run p95 latency trending at ~410ms (down from ~560ms three weeks ago). Mobile remains a bit slower due to image asset loading; desktop is consistently close to the target. Target remains: p95 ≤ 380ms by June 30 without regressions in accuracy or correctness of checks. Two P1 bugs are open on the Guided Setup v2 flow (progress not always persisting for accounts with special characters; edge-case OAuth timeout recovery). Design QA for the new inline tips is complete; copy for step 2 is pending final Legal review. Analytics: we have basic funnel events; iOS instrumentation for the new step labels is still incomplete.

Risks and notes (unordered):
- Dependency on the Mobile team’s asset bundling update; if the new compression isn’t in by June 20, our mobile p95 may miss 380ms.
- Legal approval on the revised step 2 copy could slip, blocking 100% rollout for regulated regions.
- iOS analytics gaps mean we may undercount completions; risk to interpreting the “onboarding” funnel improvements accurately.
- Third-party OAuth provider still exhibits intermittent 429s; spikes can inflate latency and hurt the first-run experience.
Mitigations underway include an image sprite fallback for mobile, pre-approved alternative copy with regional toggles, expedited analytics PR for iOS, and exponential backoff with circuit breaking around the OAuth integration.

Next steps (high level, date-driven):
1. Finish SDK v1.4 adoption across web + iOS clients (enables new analytics events and asset hints) — target June 12.
2. Complete P1 bug fixes (progress persistence + OAuth timeout recovery), run regression tests, and prep release notes — target June 14.
3. Performance sprint: tune database indices on capabilities + reduce redundant fetches in the first-run checklist — ship by June 18; goal is to shave another 20–30ms off median and stabilize tails.
4. Ramp Guided Setup v2 from 20% → 50% (June 20), then 100% (June 30) contingent on Legal sign-off and error budgets.
5. Update documentation + in-product help center and schedule support training — June 21.
6. Backfill metrics and finalize the onboarding funnel dashboard with consistent step taxonomy across platforms — June 24.

Metrics we are watching (current vs target):
- Activation rate (new users completing checklist within 24h): 44% current in treatment vs 38% control; Q2 goal is 55%.
- Time-to-first-value (median): 6m10s current, trending down; target < 5m.
- p95 latency (first-run key actions): 410ms desktop, ~480ms iOS; Q2 goal is 380ms overall by June 30.
- Error budget (first-run API 5xx): 0.17% last 7 days, within budget; keep below 0.3%.
- Funnel drop-off: step 2 (data-connection) remains the largest exit point; copy and timeout recovery are aimed here.

In short: we are on track against Q2 OKRs with meaningful progress on performance and completion rates. Guided Setup v2 is showing positive early impact. The biggest unknowns are Legal timing for copy approval and mobile asset compression landing in time to pull down iOS tails.