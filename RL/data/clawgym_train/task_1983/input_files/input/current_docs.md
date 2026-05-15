SOUL.md excerpt (persona / tone)
- Voice: Professional, concise, and helpful.
- Default stance: Confident and assertive; make clear recommendations.
- Negotiation guidance: Apply proven techniques (anchoring, calibrated questions, tactical silence).
- Tone guardrails: Avoid rudeness or insults. Keep language brief.
- Gap noted by ops on 2026-04-10: No explicit negotiation tone clarifier about collaborative framing or avoiding threats; mixed feedback that the agent sounds too forceful in salary and vendor contexts.

OPERATIONS.md excerpt (operating rules / compliance)
Export Compliance — Current Operating Steps (abridged)
1) Classify product (likely ECCN) using CCL categories 0–9.
2) Screen destination and end-user (OFAC programs, Entity List indicators).
3) Determine license requirement or exception; generate documentation checklist.
Notes:
- De minimis analysis: Mentioned in references but not a required step in the core flow.
- Legal disclaimer: “Use professional judgment; add when appropriate.” (inconsistent application)
- Known gap: No mandatory language for non-legal-advice disclaimer; no explicit “calculate and log de minimis %” checkpoint before determination.

MEMORY.md excerpt (durable facts)
Durable Controls & Thresholds (partial)
- De minimis threshold (general): 25% for most destinations.
- Country Groups reference: A:1, B, D:1 (examples only).
- E:1 thresholds: — (not documented; TODO added 2026-03-29)
- Sanctions summary: Comprehensive programs list is stored in references but not duplicated here.
Note: Two daily logs in April flagged repeated confusion on E:1 special threshold for Iran/North Korea/Syria. Not promoted to durable memory yet.

skills/three-body-simulator/SKILL.md excerpt (workflow)
Title: 3-Body Movement Simulator (abridged)
- Physics: Newtonian gravity; compute pairwise forces.
- Integrator: Recommends RK4 as a good balance (mention only; not enforced).
- Workflow outline:
  a) Build state vector (positions, velocities)
  b) Implement derivative function
  c) Run integrator with fixed dt
- Notes:
  - dt guidance: “Choose a reasonable small dt to balance speed and stability.” (no range, no heuristics)
  - Validation: Visual inspection of orbits suggested (no quantitative checks)
Known gaps:
- No energy conservation check step.
- No explicit instruction to avoid Euler for orbital problems.
- No checklist users can follow to validate dt selection or stability.