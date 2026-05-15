FinSight — Challenges and Constraints

Summary
- We are a 120-person B2B fintech SaaS with a functional org. Growth has created delivery slowdown, silos, and reliability drag. We plan to scale to ~200 in 12 months.
- Primary domains: Risk, Payments, Billing, Analytics, Admin/Onboarding; plus Platform capabilities (DevEx, Data Platform, Payments Core).
- Sales cycles require strong compliance signaling (SOC 2, PCI, vendor risk), so operational rigor matters.

Symptoms (quantitative)
- Lead time for changes: 12 days (goal: <5)
- Deployment frequency: 2 per service per week (goal: daily for most services)
- Change failure rate: 24% (goal: <10%)
- MTTR: 9 hours (goal: <2 hours)
- On-call pages: ~5 per engineer per week in SRE; app teams rarely paged today
- Feature cycle time blocked by cross-functional dependencies (frontend and backend queues)

Pain Points (qualitative)
- Delivery speed: Shared front-end and back-end queues cause sequencing delays; PMs struggle to prioritize across many stakeholders.
- Silos: QA and Design are centralized; knowledge stays within functions; context lost between handoffs.
- Decision latency: Ambiguity on who decides (PM vs EM vs Tech Lead); meetings proliferate; lack of documented decision SLAs.
- On-call load: SRE is primary responder; application squads do not own production runbooks; sev definitions vary by team.
- Feature flags: Homegrown toggles cannot safely ring-fence beta cohorts or run kill switches; rollbacks are blunt (re-deploy).
- Billing: Monolithic code path with tight coupling to orders schema; hard to implement usage-based pricing and proration correctly.
- Payments: The “Payments” initiative has swelled to 12 engineers but operates as a single backlog with conflicting US/EU priorities and gateway integrations competing for attention.

Constraints and Non-Negotiables
- Launch timelines:
  - Q2: Adopt enterprise-grade feature flags; standardize incident severity matrix and runbooks
  - Q3: EU payments (PSD2) GA; usage-based billing MVP GA
  - Q4: SOC 2 Type II recertification; Analytics v2
- Budget guardrails:
  - Up to +80 net new hires; maintain ≥18 months cash runway
  - Cloud cost growth ≤20% YoY; investments must reduce unit cost at scale
  - Manager span of control ≤8
- Compliance:
  - Formal third-party risk policy must be approved and enforced by end of Q2
  - PCI DSS SAQ A-EP scope reduction preferred; minimize cardholder data exposure

Operating Model Aspirations
- Move to product squads with 6–8 people each and clear ownership boundaries
- Introduce platform teams where leverage is high: DevEx, Data Platform, Payments Platform
- Embed QA and Design into squads; shift testing left; async-first documentation (ADRs, RFCs, postmortems)
- Clear decision rights using RACI/RAPID; escalation SLAs to unstick cross-team decisions

Risks to Manage
- Cultural drift with rapid hiring; need cohort-based onboarding and explicit values
- Half-matrix confusion if platform vs product reporting lines are unclear
- Over-rotation to meetings; must reserve maker time and leverage async docs

What “Good” Looks Like in 12 Months
- 8–10 product/platform squads, each 6–8 people, independently shipping
- Two-pizza compliance enforced; “Payments” split into Platform vs Applications with crisp API contracts
- Feature flags vendor in place; canary/beta cohorts, kill switches, phased rollouts
- Billing is modularized with evented usage pipeline; pricing/ratings engine decoupled
- Incident severities standardized (Sev1–Sev4), with on-call duty owned by squads; MTTR < 2h
- Third-party risk policy approved; vendor intake with scoring and controls is routine
- Documented decision SLAs: L1=5d, L2=10d, L3=14d, L4=30d; visible escalation paths

Dependencies and Notes
- Frontend component library updates block multiple domains; DevEx platform investment needed
- Data Platform must support both Risk models and Billing usage metering without contention
- EU go-to-market needs localized payment methods and PSD2 SCA; requires coordination between Payments Platform and Payments Applications
- Customer Success requests Analytics v2 self-serve to reduce BI ad-hoc workload