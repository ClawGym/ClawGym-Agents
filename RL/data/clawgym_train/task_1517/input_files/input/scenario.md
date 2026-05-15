Title: Local-First Multi-Agent Assistant — Week 22 Brief

Context
We are standing up a persistent, local-first memory engine for a multi-agent assistant. The team is using keyword-only search initially (no embeddings), with JSON storage on disk. Agents collaborate across security, platform, and product workstreams. Agent IDs used in this brief:
- maki — Platform/Infra engineer (deployments, migrations, feature flags)
- kuro — Security engineer (findings, mitigations, policy)
- ivy — Product/Customer experience (preferences, onboarding, voice & tone)

Overall goals for this week:
- Complete v2.0 rollout of the API gateway and Postgres migration.
- Resolve a login XSS finding and roll out browser-side protections.
- Onboard customer Avery’s preferences and language settings.
- Capture one HR-related compensation update for contractor Jordan (note: two sources disagree; requires review).

Day 1 — Monday
- Decision (maki): Migrate primary data store from MySQL to Postgres in the next release window. Rationale: transaction integrity and ecosystem libraries.
- Task (maki): Draft migration runbook and dry-run against staging dataset by end of day.
- Fact (maki): Postgres default port for our managed instance is 5432 (prod and staging). Source: Platform config doc.
- Finding (kuro): Reflected XSS discovered in login form via the “next” redirect parameter (auth/xss-redirect). Risk: user session hijack if exploited.
- Task (kuro): Add input validation and output encoding for redirect parameter; propose Content Security Policy (CSP) changes.
- Preference (ivy): Customer “Avery” prefers dark mode for the web dashboard.
- Claimable profile (ivy): Avery’s preferred_language is “English”; spoken_languages are “English” and “Spanish” per CRM note.
- Note (ivy): Avery’s time zone is America/Chicago (US Central).

Day 2 — Tuesday
- Event (maki): API gateway v2.0 deployed to production at 14:30 local time with canary at 20% traffic.
- Decision (maki): Enable feature flag “search_v2” at 20% rollout; roll back if error rate > 2% over 15 minutes.
- Task (maki): Monitor gateway error rate and latency for 2 hours post-deploy.
- Fact (ivy): Accessibility audit shows no-blocker issues for v2.0 routes; contrast meets AA on new pages.
- Insight (kuro): The XSS vector is more prevalent for unauthenticated redirect flows; authenticated flows are less exposed due to existing allowlist.

Day 3 — Wednesday
- Event (maki): Postgres migration dry-run completed in staging; data integrity verified (row counts and spot checks).
- Decision (kuro): Adopt a restrictive CSP policy that disallows inline scripts and only permits assets from our domains. Rollout plan: staging today, prod Friday pending tests.
- Task (kuro): Prepare CSP report-only headers for 48 hours on staging to collect violations before enforcing.
- HR record (ivy): Contractor “Jordan” salary is $120,000 USD (base) per HR system. This is a structured claim; treat HR as high-trust provenance.
- Slack note (ivy): Manager message from last quarter mentions “Jordan at $115k”. This conflicts with the HR record and should be quarantined or reviewed before activation.

Day 4 — Thursday
- Event (kuro): Patch deployed for login XSS: validated redirect parameters and introduced output encoding.
- Fact (maki): After v2.0 canary, 95th percentile latency improved by ~8%; error rate stayed under 0.8%.
- Preference (ivy): Avery appreciates concise release notes and prefers email notifications over in-app popups for changes.
- Update (ivy): A support call suggested Avery also speaks French at a conversational level; this corroborates (not replaces) the existing spoken_languages list if schema allows multiple entries.
- Task (maki): Schedule final Postgres cutover for Friday 22:00–23:00 local maintenance window.

Additional details and hints for memory structuring
- Use agent names verbatim as listed above for memory ownership: maki, kuro, ivy.
- Atomicity: Break larger items into single facts/decisions/tasks/events/insights/preferences where possible.
- Claims suggested from this brief:
  - subject: user:avery, predicate: preferred_language, value: english
  - subject: user:avery, predicate: spoken_languages, value: english
  - subject: user:avery, predicate: spoken_languages, value: spanish
  - subject: user:avery, predicate: timezone, value: america/chicago
  - subject: person:jordan, predicate: salary, value: usd 120000 (HR record; high trust)
  - subject: person:jordan, predicate: salary, value: usd 115000 (Slack note; lower trust; likely quarantine)
  - subject: system:postgres, predicate: port, value: 5432
  - subject: feature:search_v2, predicate: rollout_percent, value: 20
- Linking guidance:
  - Link v2.0 deployment, feature flag decisions, and Postgres migration tasks.
  - Link XSS finding to the patch event and CSP decision.
  - Link Avery’s preferences and languages under a customer-onboarding episode.
- Quarantine guidance:
  - For the salary conflict on contractor Jordan, prefer the HR record as canonical. The Slack note should be low-trust and placed in quarantine pending review.
- Decay guidance (policy intent for config):
  - Half-life around 30 days; archive below ~0.15 strength, delete below ~0.05.
  - Reinforce high-value decisions that are referenced or reused (e.g., CSP policy, migration outcomes).

Episode candidates (to be reflected in output episodes)
- Deploy v2.0 Rollout: API gateway v2.0 canary, feature flag decisions, Postgres migration dry-run and cutover plan, performance outcomes.
- Security Triage Week 22: XSS finding, patch deployment, CSP decision, staging report-only period.
- Avery Onboarding & Preferences: preferred_language, spoken_languages, dark mode preference, notification channel (email), timezone.

Provenance and trust hints
- HR system entries: high trust.
- Slack manager notes: medium to low trust (informational, may conflict with HR).
- Support calls/CRM notes: moderate trust for profile/preferences; corroboration is beneficial.
- Platform config docs and deployment telemetry: high trust.

Search examples (for cross-agent reasoning)
- “Avery language preferences” should retrieve preferences and spoken languages (ivy) and any customer-facing decisions that reference communication style.
- “Gateway v2 latency improvement” should retrieve deployment event and performance fact (maki), and link to the feature flag decision.
- “XSS login redirect” should recall the finding (kuro), the patch event (kuro), and the CSP decision (kuro), plus any related tasks.

This brief is intended to seed at least 15 atomic memories across maki, kuro, and ivy, including at least five structured claims and one intentional conflict on salary for quarantine testing.