# DevGraph — Product Brief and GTM Context (v1.3)

Last updated: 2026-04-14
Author: Product & GTM (Elena / Morgan)
Status: Beta planning (v0.9 schema locked, beta launch target: 2026-06-03)

## 1) One-Line Summary
DevGraph is a graph-native knowledge system for engineering teams that unifies code, services, infrastructure, incidents, and RFCs into a living dependency graph you can query in plain English to see change impact, reduce MTTR, and prevent architecture drift.

## 2) Problem
- Engineering knowledge is fragmented across repos, CI/CD, service catalogs, runbooks, and incident tools.
- Change impact is slow and error-prone; new engineers lack systems context; incident response is delayed by “who owns what?” questions.
- Existing tools (service catalogs, wikis) are static, siloed, and require manual upkeep; knowledge decays fast.

## 3) Solution
A continuously updated dependency graph that ingests code (monos/multi-repos), deployment manifests, runtime telemetry, incidents, and planning artifacts. It exposes:
- Change impact analysis: “What breaks if we deprecate Kafka topic X?” shows dependent services, owners, SLAs, and blast radius.
- Incident context on demand: “What changed near service payments-api before the P1?” fuses git, deploys, and alerts.
- Architecture drift detection: flags divergence between intended and actual topology.
- Query in natural language and graph DSL, with explainable paths.

## 4) Core Capabilities (Beta)
- Ingestors: GitHub/GitLab; Helm/Kustomize; Kubernetes; Terraform state; Datadog; PagerDuty; Sentry; Atlassian (Jira/Confluence); RFCs (Markdown).
- Identity & ownership: map services to teams via CODEOWNERS, PagerDuty schedules, and repo metadata.
- Graph engine: property graph with time-aware edges; supports “as-of” queries and diff views.
- Query UX: natural language + saved queries; “why” explanations; export to Slack, Jira.
- Governance: policy checks for risky changes (e.g., critical dependency touched without owner sign-off).
- Security: SSO (Okta, Google), SCIM, audit log. SOC 2 Type I completed (2026-03-20); Type II in progress (target 2027-01). Data residency: US; EU region planned Q3 2026.

## 5) What’s Different
- Full-stack graph (code→infra→runtime→incidents) vs catalog-only.
- Reasoning layer connects topology with ownership and SLOs, not just endpoints.
- Time-aware graph enables pre/post incident comparisons and drift tracking.
- “Explainable” natural-language answers with graph-path evidence.

## 6) Target Users and ICP
Primary personas:
- Head of Platform / Platform Engineering leads
- SRE Managers and on-call Staff Engineers
- Staff/Principal Engineers responsible for architecture

ICP v1 (launch focus):
- Mid-market, cloud-native SaaS or fintech, 100–800 engineers, Kubernetes-first, microservices ≥40, US/EU.
- Security posture: SOC 2 Type II preferred; can accept Type I + strong controls for pilots.
- Tooling: GitHub, Datadog, PagerDuty common; willing to trial SaaS in vendor VPC with SSO.

Secondary (post-beta):
- Regulated enterprises (banks/health): likely require VPC/private install or private SaaS with strict data boundaries.
- Backstage-heavy orgs seeking augmentation rather than replacement.

## 7) Competitive Landscape
- Atlassian Compass (service catalog): lightweight, Atlassian-integrated; lacks deep runtime + code graph.
- Cortex (service maturity): strong scorecards; less code/incident graph depth.
- Backstage (open source): extensible, but static without heavy investment; teams build bespoke plugins; high maintenance.
- Internal build: 2–3 FTE to build/maintain minimal viable graph + UI; reasoning and time-aware diffs add complexity.

Positioning:
- “From catalog to cognition.” DevGraph is the living system view with explainable answers, not a spreadsheet of services.

## 8) Current Traction and Proof
- 12 design partners (SaaS/fintech): 7 US, 5 EU.
- Pilot outcomes to date:
  - Incident MTTR reduced by 18% median across 4 teams after 6 weeks (confounding factors present; unknown exact attribution).
  - New engineer time-to-first-PR on affected services reduced by ~2 days at 3 partners.
  - 76% of natural language queries returned usable answers; 24% needed DSL or tuning (v0.9).
- NPS (pilot users): 32; Primary value quotes: “blast radius in seconds,” “owners + SLOs stitched automatically.”

## 9) Deployment Options (Beta)
- SaaS (US region) only at beta start.
- Private region EU (Frankfurt) targeted for Q3 2026 (depends on infra vendor contract).
- VPC install / private SaaS: not at launch; exploration in H2 2026. Risk: large/reg orgs will block without it.

## 10) Pricing & Packaging — Options Under Consideration
Option A: Seat-based (platform + SRE seats)
- Pros: Simple, aligns with knowledge worker value; predictable.
- Cons: Value accrues across org via queries and automation, not only seats; discourages broad view-only access.
- Strawman: Core $25/user/month (min 25 users); Teams $45/user/month; Enterprise custom. Add-on: ingestion packs.

Option B: Service-based (per registered service / node)
- Pros: Maps to scope and value; scales with complexity; encourages org-wide visibility.
- Cons: Harder to estimate upfront; can feel like a “tax” on microservices.
- Strawman: $8/service/month (min 150 services), includes 3 integrations; add-ons for advanced reasoning.

Option C: Hybrid (platform fee + service blocks)
- Pros: Blend predictability and scale; avoids seat friction for viewers.
- Cons: More complex to explain; billing integration needed.
- Strawman: Platform $1,500/month + $5/service/month (first 200 included in platform); SSO included on Teams+.

Early signals:
- 4/7 design partners prefer hybrid; 2 prefer pure service-based; 1 indifferent.
- Budget anchors heard: $20–60k ARR for 200–600 services and ~50 engaged users.
- Unknown: price sensitivity in 100–200 engineer orgs; impact of LLM usage cost on margins.

## 11) GTM Motions — Hypotheses
Motion 1: Top-down platform sale
- Target: Head of Platform, SRE leadership. Business case: MTTR, change failure rate, onboarding time.
- Pros: Budget authority; larger initial ACVs.
- Cons: Longer cycles (3–6 months); heavier security reviews (SOC 2 Type II pressure).

Motion 2: Bottom-up adoption
- Target: Staff engineers/SREs; lightweight free tier; quick graph for a subset of services; shareable explorable views.
- Pros: Faster entry; virality via shared queries.
- Cons: Requires self-serve UX, freemium guardrails, support costs; conversion unknown.

Motion 3: Dual path
- Seed with bottom-up team pilots while enabling top-down business case and procurement path.
- Pros: Flywheel; testimonials from users fuel exec buy-in.
- Cons: Requires clarity in packaging and limits for self-serve; messaging bifurcation.

Channel bets:
- Content: “Explainable impact analysis” deep dives, incident postmortems with graph replays.
- Events: KubeCon NA (Oct 2026) booth + talk; DevOpsDays circuit.
- Community: Sponsor an OSS Backstage plugin that pipes topology into DevGraph (augment, not replace).
- Partners: SIs specialized in platform engineering; Datadog and PagerDuty tech alliances.

## 12) Pilot Design (Current Draft)
- Duration: 4–6 weeks.
- Scope: 40–100 services, 3–5 integrations (GitHub, K8s, Datadog, PagerDuty, Terraform).
- Setup: 1-day ingestion + mapping workshop; 1–2 saved “impact” queries; on-call notebook template.
- Success metrics (pilot exit criteria):
  - 2+ incident responses leveraged DevGraph to identify owner/impact within 5 minutes.
  - 1 architecture drift prevented or remediated with evidence.
  - 10 active users/week running queries; 2 saved queries adopted in recurring rituals (change review, incident retro).
- Risks: Data completeness gaps, ownership ambiguity, noisy graphs. Mitigation: manual owner override, “confidence” scores in answers.

## 13) Risks & Constraints
- Security: SOC 2 Type II gap may block larger/reg orgs; must offer strong controls and clear roadmap.
- Integrations: Quality and freshness vary; missing sources degrade trust; need ingestion health dashboard.
- Cost structure: LLM inference and graph storage costs need guardrails; unknown query distribution under scale.
- Competition: Backstage investments can displace budget; must coexist with or augment Backstage.
- Messaging risk: “AI for ops” fatigue; emphasize explainability and evidence paths.

## 14) Key Unknowns
- Conversion rates for bottom-up self-serve in 100–300 engineer companies (unknown).
- Willingness-to-pay per service vs seat in fintech vs general SaaS (partial signals, still unknown).
- EU data residency demand split at launch (unknown).
- Pilot-to-ACV conversion cycle time with SOC 2 Type I only (unknown; estimates 60–120 days).

## 15) Launch Timeline & Resources
- Beta feature freeze: 2026-05-10
- Beta launch: 2026-06-03 (US region)
- EU region preview: 2026-09 (dependent on infra contract)
- KubeCon NA: 2026-10 sponsorship reserved
- Team: 8 FTE (4 eng, 1 infra, 1 ML, 1 PM, 1 GTM). Runway: 16 months (seed $4.2M).
- Year-1 target: $100k MRR by 2027-04.

## 16) Draft Messaging
Tagline candidates:
- “DevGraph — The living map of your software, with answers you can trust.”
- “Know what breaks before it breaks.”
- “From change to impact in seconds, with explainable evidence.”

One-sentence pitch:
DevGraph connects code, services, and incidents into a living map so your teams can see blast radius, find owners, and stop drift—backed by explainable answers, not guesses.

---

Appendix A — Example Queries
- “What breaks if payments-api removes dependency on topic orders.v1?”
- “Show all services touching PCI boundaries and their on-call rotations.”
- “What changed within 30 minutes before incident INC-2317 affecting checkout-latency SLO?”
- “Where does Terraform state drift from desired architecture diagram in RFC-1042?”