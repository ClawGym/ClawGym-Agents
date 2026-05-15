Week of 2026-04-06 → 2026-04-10
Company: Northstar Labs
Product focus: Atlas (web app), Pulse (internal telemetry), Legacy Android
Stakeholders referenced: CTO Bob O’Hara, PM Jenna Park, QA Rina Cho, Eng Lead Luis Ortega, Sales Tara Malik, Legal Sam Patel, CFO Priya Nair

Monday 2026-04-06
09:08 Me → Jenna: I decided to prioritize Atlas onboarding over the Notifications revamp for this sprint. Churn is hitting us at first-session; onboarding fixes move the retention needle sooner.
09:11 Jenna: Okay – that means Notifications slips. Alternatives were keeping Notifications, splitting the sprint, or focusing mobile. Who needs to be informed?
09:14 Me: I’ll tell Bob in the weekly update. We’ll keep mobile changes minimal this week.
10:26 Me → Luis: Technical choice: we’re standardizing on Postgres 15 for the analytics store. Team expertise + existing tooling wins; no time to wrangle MySQL or learn Aurora quirks before Friday’s demo.
10:29 Luis: Works for me. We can revisit Aurora later if we need autoscaling. Noted.
11:42 Me → Priya: I’m holding off on hiring a dashboard contractor. We’ll stretch internal capacity this sprint and reassess post-demo. Budget is tight and onboarding is higher leverage.
11:45 Priya: Thanks. If you change your mind, Legal needs a vendor contract reviewed, and Finance can reallocate line items.

Tuesday 2026-04-07
08:55 Me → Team: I decided to skip unit tests for the dashboard feature to ship Thursday. We’ll cover with smoke tests and a QA pass to make the Friday demo.
08:57 Rina: I can do a thorough manual pass today and tomorrow. Let me know the areas most risky.
09:22 Me → Rina: Assigning you to dashboard test coverage for the week; I’ll pull mobile testing back to spot checks.
09:40 Me → Bob: I’m sending the weekly update directly to you today instead of routing through Jenna. It’s technical-heavy (auth, telemetry), and I want your gut check early.
09:44 Bob: Fine by me. CC Jenna so she’s not surprised.
10:18 Me → Team: Vendor call recap – I’m choosing KiteMetrics for product analytics and will start a 3-month contract this week. Strong support, fast deployment, and we don’t have bandwidth to build in-house.
10:20 Jenna: Do we need Legal’s signoff?
10:21 Me: Yes. Sam flagged data residency language; I’ll get the addendum negotiated today.
11:05 Me → Luis: Charting – going with SparklineJS for the dashboard. Lightweight, quick to wire, minimal bundle impact.
11:07 Luis: Alternatives were Chartist or ECharts; SparklineJS is fine for MVP.

Wednesday 2026-04-08
08:31 Me → Security channel: Architecture decision – we’re switching auth from server sessions to JWT (RS256) ahead of the demo. Compliance audit requires revocation-friendly tokens. Sessions don’t meet the audit notes without more work.
08:34 Bob: That’s a big move. Do we have ADR written?
08:36 Me: Writing ADR this morning. Alternatives considered: stick with sessions temporarily; use OAuth via AuthX; both have trade-offs against audit.
09:20 Me → Jenna: I decided to drop “Legacy sync” from scope this quarter. It’s a maintenance trap; we can’t afford it alongside onboarding and auth work. We’ll communicate clearly to customers and offer a migration path.
09:22 Jenna: Understood. Sales will want messaging. Tara should be looped in.
10:05 Me → Calendar: Rescheduled the design review from Thursday to next Wednesday. Demo prep is taking the slot; we need focused time Friday morning.
12:02 Me → Team: SSO integration is deferred to the next sprint. We don’t have cycles to do it right before the demo.

Thursday 2026-04-09
09:10 Me → Team: Shipping dashboard changes end of day today for tomorrow’s demo. Smoke tests only; QA pass complete by Rina.
09:28 Me → Bob: Prepared the Pulse topology diagram myself and sent it your way. I wanted to make sure the narrative matches the demo flow.
09:30 Bob: Got it. This helps the demo story.
10:12 Me → Tara: We’re committing to publish a public roadmap Friday afternoon. We’ll keep it to near-term items we’re confident about: onboarding, analytics, auth migration.
10:15 Tara: Perfect. Sales will share the link with key accounts after you publish.
11:47 Me → Luis: Bug triage – I’m delegating triage ownership to you for the week so I can focus on roadmap and demo content. I’ll step back in next Monday.
14:19 Me → Team: Code freeze starts today at 16:00 ahead of the demo. Only hotfixes approved by me till tomorrow afternoon.

Friday 2026-04-10
08:08 Me → Priya: Approving budget reallocation from Notifications to Onboarding for Q2. Onboarding is a bet we need to place; Notifications revamp can wait until we see retention gains.
08:11 Priya: I’ll update the model and send you the new cash flow forecast.
09:02 Me → Product channel: I decided to sunset the Legacy Android app by end of May. We’ll announce timelines next week and offer migration support.
09:06 Jenna: I’ll coordinate messaging and an FAQ for customer support.
10:25 Me → Team: Incident at 10:10 – caching change caused stale dashboard data. I rolled back the cache layer immediately; we’ll reintroduce after demo with better invalidation.
10:27 Luis: Understood. That rollback fixed the stale data.
11:18 Me → Standup: Standups move to 9:30 for the next two weeks to give QA space in the early morning.
11:45 Me → Demo prep: We’ll keep the investor demo narrative tight and avoid deep-diving the auth switch unless asked. Focus is onboarding progress and analytics visibility.
15:56 Me → Team: Demo complete. Next week we’ll write unit tests for the dashboard, draft the ADR for auth, and publish the roadmap link in the product site footer.

Notes/alternatives referenced explicitly or implicitly:
- Prioritization alternatives: keep Notifications on track; split sprint capacity; focus mobile instead of web onboarding
- Database alternatives: MySQL, Aurora
- Vendor alternatives: build in-house; OpenTrack competitor; postpone contract
- Auth alternatives: sessions; OAuth/AuthX
- Testing alternatives: write unit tests first; smoke tests
- Communication alternatives: route updates through PM; wait for sprint review
- Scope alternatives: retain Legacy sync; reduce scope rather than drop
- Staffing alternatives: hire contractor; keep Rina on mobile
- Process alternatives: no code freeze; shorter freeze; only pre-demo guardrails
- Demo content alternatives: mention auth switch; keep it out of narrative
- Standup time alternatives: keep 9:00; move to afternoons