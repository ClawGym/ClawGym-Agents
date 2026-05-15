Process Policies and Delegation Boundaries

Scope and Safety
- No autonomous actions without explicit user approval.
- All proposals must define clear scope and boundaries before any execution.
- For any expansion of scope or phase, obtain explicit approval again.
- Internal-only communications (e.g., eng-leads status) are lower risk than external or client-facing communications.
- Production deployments are high risk and always require explicit step-by-step human approval.

Pilot and Expansion
- Use a pilot: first 5 runs under the agreed scope with post-execution notification to the user each time.
- Expansion phases:
  1) Shadow — Watch the task and document steps (3–5 observations)
  2) Assist — Prepare inputs, human executes (5–10 instances)
  3) Supervised — Agent executes, human reviews before completion; exit when ≥95% approvals with <5% modifications
  4) Autonomous + Notify — Agent executes independently and notifies after; exit after 10+ instances with zero negative feedback
  5) Full Ownership — Agent owns the task; human involved only for exceptions
- Rollback: If something goes wrong, stop, notify the human, drop back one phase, address the gap, and resume only with approval.

Risk Boundaries
- Staging deployments: low to medium risk; allowed under pilot and supervision with explicit approval to begin the pilot.
- Production deployments: high risk; require explicit human sign-off for every step each time; not suitable for full autonomy.
- Internal status emails (eng-leads) with non-sensitive content: low risk; suitable for pilot after approval.
- Weekly changelog compilation from merged PRs: low to medium risk (internal docs); suitable for pilot after approval.
- Monday analytics snapshot from provided CSVs: low risk if data is internal and outputs are summaries; suitable for pilot after approval.
- PR label triage: low risk process work; suitable for pilot after approval.

Prioritization Scoring (Integers Only)
Use the following 1–3 scales to score candidates and compute:
Priority = Frequency × Time cost × (4 - Skill required) × (4 - Risk)

- Frequency:
  1 = Low (monthly/ad hoc)
  2 = Medium (weekly)
  3 = High (daily or multiple times per week)

- Time cost (per instance):
  1 = Low (<10 minutes)
  2 = Medium (10–30 minutes)
  3 = High (>30 minutes)

- Skill required (human judgment complexity):
  1 = Low (pure process, deterministic rules)
  2 = Medium (some rules and templates, occasional discretion)
  3 = High (requires nuanced judgment)

- Risk (impact if wrong; reversibility):
  1 = Low (easily reversible, internal-only, no sensitive data)
  2 = Medium (some impact, internal stakeholders)
  3 = High (external impact, sensitive systems/data, production changes)

Notes and Conventions
- Confirm exact scope before starting any pilot (e.g., which repos for PR triage, which channels for status messages, which paths for data sources).
- Keep logs of proposed tasks and outcomes in text-based files only under relative project paths.
- Do not access calendars, email inboxes, or external systems unless explicitly granted and scoped. Use only conversation context and the provided inputs to infer patterns.
- When drafting communications, keep internal-only content and avoid sensitive details unless explicitly provided.
- For deployments: follow checklists; staging deploys should include build, deploy, smoke tests, and a brief internal announcement. Production deploys are excluded from autonomy proposals unless limited to pre-deploy checklists with human gate approvals.