# Memory Index — Hippocampus
Last updated: 2026-04-10

This file routes which schemas to load based on topic triggers. Load only the relevant schemas.

---

## Schema Registry

### Project Demo
- Files: `memory/schemas/project-demo.md`
- Triggers: demo, milestone, pipeline, vector index, launch, stakeholders
- Priority: HIGH
- Cross-links: → Personal Health (workload balance during crunch)
- Status: Active
- Why it matters: Guides the end-to-end demo delivery and status.

### Personal Health
- Files: `memory/schemas/personal-health.md`
- Triggers: workout, run, sleep, nutrition, health, HRV
- Priority: MEDIUM
- Cross-links: → Project Demo (stress and schedule impact)
- Status: Active
- Why it matters: Sustains performance and prevents burnout.

---

## Cross-Link Map
Project Demo ↔ Personal Health — balance schedule, avoid burnout, track sleep quality near demo.

---

## Permanent Anchors
Check `memory/ANCHORS.md` when:
- A CRITICAL domain is triggered
- A past milestone or commitment is mentioned
- Something feels inconsistent with known history

---

## Vector Store
Location: `memory_brain/vectorstore/` (LanceDB)

---

## Auto-Schema Protocol
New significant domain → create `memory/schemas/<topic>.md` → add entry above → re-index.