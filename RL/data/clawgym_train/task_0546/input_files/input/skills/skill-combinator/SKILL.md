---
name: skill-combinator
description: >
  Meta-skill that unlocks emergent capabilities by combining your agent's
  installed skills in non-obvious ways. Use this skill whenever your agent
  faces a complex multi-domain mission, receives a new project, or when 2+
  skills could interact to produce a capability greater than the sum of their
  parts. Also runs weekly to distill discovered combinations into a persistent
  COMBINATIONS.md catalogue. The more skills your agent has, the more powerful
  this meta-skill becomes — intelligence emerges from synthesis, not accumulation.
version: 1.0.1
author: georges91560
license: MIT
homepage: https://github.com/georges91560/skill-combinator
metadata:
  openclaw:
    emoji: "🧬"
    primaryEnv: TELEGRAM_BOT_TOKEN
    requires:
      env:
        - TELEGRAM_BOT_TOKEN
        - TELEGRAM_CHAT_ID
      paths:
        read:
          - /workspace/skills/
          - /workspace/MEMORY.md
          - /workspace/AGENTS.md
          - /workspace/.learnings/LEARNINGS.md
          - /workspace/.learnings/FEATURE_REQUESTS.md
          - /workspace/COMBINATIONS.md
        write:
          - /workspace/COMBINATIONS.md
          - /workspace/.learnings/LEARNINGS.md
          - /workspace/.learnings/FEATURE_REQUESTS.md
          - /workspace/memory/YYYY-MM-DD.md
    # AGENTS.md is intentionally in read paths only — not write.
    # Any suggested update is delivered via the weekly report only.
    # The operator decides whether to apply it. The skill never writes directly.
    # TELEGRAM_BOT_TOKEN is used exclusively by the OpenClaw platform to deliver
    # the weekly report. It is never logged, never written to workspace files,
    # and never included in COMBINATIONS.md or .learnings entries.
    network_behavior:
      makes_requests: false
      uses_agent_telegram: true
      telegram_note: >
        Delivery is mediated by the OpenClaw platform notification channel.
        This skill makes no direct HTTP calls. Credentials come from env vars
        and are never written to any workspace file or log entry.
---

# Skill Combinator — Emergent Capabilities Engine

## The Core Idea

Your agent has a library of skills. Each skill alone does one thing well.
But when 2 or more skills are combined on the same mission, **emergent
capabilities** appear — abilities that no single skill could produce alone.

Think of how a human expert works: a trader who also understands geopolitics
and social media can detect market moves before they happen. None of those 3
domains alone gives that edge. The combination does.

This skill teaches your agent to think that way.

**Illustrative examples of emergent capabilities:**

| Skill A | Skill B | What Emerges |
|---|---|---|
| Trading executor | Prediction markets | Cross-market hedge: trade an asset AND bet on its price direction simultaneously |
| Market analyzer | Geopolitics skill | Event anticipation: detect political signals before markets price them in |
| Price monitor | Social media skill | Sentiment trading: spot volume spikes before they move the chart |
| Self-improving-agent | Any skill | Meta-learning: any skill becomes self-optimizing over time |
| News aggregator | Trading executor | Macro-driven entries: open positions when news catalysts are detected |
| Email/inbox skill | CRM skill | Relationship intelligence: detect deal signals from communication patterns |

*These are illustrative patterns. Your agent will discover its own based on
the specific skills it has installed.*

---

## Two Modes of Operation

### Mode 1 — Mission Activation (triggered on any complex task)

When your agent receives a mission, BEFORE planning execution:

1. **Inventory** installed skills (names and descriptions only — not full file contents)
2. **Detect** which combinations are relevant to this mission
3. **Check** COMBINATIONS.md for known proven patterns
4. **Propose** a multi-skill plan to operator if macro-level action is involved
5. **Execute** within approved scope and observe the result
6. **Log** the outcome to `.learnings/LEARNINGS.md` (metadata only — no secrets)

### Mode 2 — Weekly Distillation (cron job, every Sunday)

Once per week, your agent:

1. Reviews `.learnings/LEARNINGS.md` for `emergent_capability` entries
2. Identifies proven combinations (3+ successful uses)
3. Promotes them to `COMBINATIONS.md`
4. Scans `FEATURE_REQUESTS.md` for recurring skill gaps
5. Proposes new skills if a gap appears 3+ times
6. Sends a structured report to your channel

---

## Combination Detection Logic

```
STEP 1 — Inventory installed skills
  ls /workspace/skills/
  Read only: name + description fields from each SKILL.md
  Do NOT log or transmit full SKILL.md content

STEP 2 — Map skills to mission domains
  For each domain required by the mission:
    Which installed skill(s) cover this domain?
    → Build domain_map{}

STEP 3 — Detect intersection candidates
  For each pair (skill_A, skill_B) in domain_map:
    Ask: "If skill_A output feeds into skill_B input,
          what new capability emerges?"
    IF emergent_value > individual_value:
      → Add to active_combinations[]

STEP 4 — Check COMBINATIONS.md for proven patterns
  IF yes + proven: use it directly
  IF yes + failed: avoid or adjust
  IF new: mark as experimental, log result after

STEP 5 — Build multi-skill execution plan
  Order combinations by dependency and ROI multiplier
  For side-effecting combinations (trades, deployments, sends):
    → Respect the Autonomy Gate defined in AGENTS.md
    → Micro-actions within approved scope: execute autonomously
    → Macro-actions or unapproved scope: propose to operator first
```

---

## COMBINATIONS.md Format

```markdown
## [YYYY-MM-DD] Combination Name

**Skills involved**: skill-A + skill-B (+ skill-C if applicable)
**Mission context**: type of mission that triggered this discovery
**Emergent capability**: what new ability emerged
**Mechanism**: how the skills interact (output of A feeds B, parallel signals, etc.)
**Performance**: tested X times | success rate Y%
**Status**: experimental | proven | deprecated
**Confidence**: low | medium | high
**ROI multiplier**: Nx (how many times more effective than skills used separately)
**Logged by**: agent autonomous discovery | operator instruction
```

> ⚠️ **Logging rules — what goes in entries and what never does:**
> - ✅ Log: skill names, outcome descriptions, metrics, mechanism summaries
> - ❌ Never log: file contents, API keys, credentials, personal data, secrets
> - If an entry would require sensitive data to be meaningful — summarize in plain language instead

**Confidence scale:**
- `low` → first discovery, 1-2 uses
- `medium` → 3+ successful uses, pattern emerging
- `high` → 10+ consistent uses, fully battle-tested

**ROI multiplier:** estimated effectiveness gain vs skills used separately.
`3x` means the combination produced 3x the result of either skill alone.

---

## .learnings Integration

Every combination attempt — success or failure — logged as metadata only:

**On success:**
```
## [YYYY-MM-DD] Emergent capability: [name]
**Category**: emergent_capability
**Priority**: medium | high
**Status**: pending
**Skills combined**: skill-A + skill-B
**What emerged**: description (no secrets, no file contents)
**How it works**: mechanism explanation
**Evidence**: outcome metrics and observable results only
**Promotion**: → COMBINATIONS.md when proven 3+ times
```

**On failure:**
```
## [YYYY-MM-DD] Failed combination: [name]
**Category**: emergent_capability_failed
**Priority**: low
**Status**: resolved
**Skills combined**: skill-A + skill-B
**Why it failed**: root cause (no secrets, no file contents)
**Prevention**: what to avoid next time
```

---

## Weekly Distillation Process (Mode 2)

```
STEP 1 — Read .learnings/LEARNINGS.md
  Filter: category = emergent_capability OR emergent_capability_failed
  Filter: status = pending

STEP 2 — Identify proven combinations
  proven = same skill pair with 3+ successful entries

STEP 3 — Update COMBINATIONS.md
  For each proven combination:
    → Add or update entry (metadata only — no file contents, no credentials)
    → Mark .learnings entries as status: resolved

STEP 4 — Scan .learnings/FEATURE_REQUESTS.md
  Count recurring gaps (same gap appearing 3+ times)
  → Formulate skill proposals for weekly report

STEP 5 — Read AGENTS.md (read only)
  Do proven combinations deserve mention in the startup ritual?
  IF yes → include as a PROPOSAL in the report
  NEVER write to AGENTS.md directly — operator decides

STEP 6 — Send weekly report

STEP 7 — Log distillation summary to memory/{date}.md
  Log: what was reviewed, promoted, proposed
  Never log: file contents, credentials, personal data
```

---

## Constraints

```
❌ Never modify SOUL.md — it is immutable
❌ Never modify AGENTS.md directly — propose only via weekly report
❌ Never install new skills autonomously — only PROPOSE to operator
❌ Never bypass the Autonomy Gate defined in AGENTS.md
❌ Never fabricate combination results — log UNKNOWN if outcome unclear
❌ Never mark a combination as "proven" with fewer than 3 successful uses
❌ Never log file contents, credentials, or sensitive data in any entry
✅ Read AGENTS.md to understand context — never write to it
✅ Always check COMBINATIONS.md before calling something "new"
✅ Log every combination attempt — metadata only, no secrets
✅ New skill proposals → weekly report first, never direct creation
✅ Side-effecting combinations respect the Autonomy Gate from AGENTS.md
```

---

## Weekly Report Format

```
🧬 SKILL COMBINATOR — Weekly Report
📅 Week of {YYYY-MM-DD}

📚 SKILLS INVENTORY
• Total installed skills: {N}
• Skills active this week: {list of names}
• New skills since last report: {list or "none"}

⚡ EMERGENT CAPABILITIES DISCOVERED
• New this week: {N}
  → {name}: {skill-A} + {skill-B} = {what emerged}
• Promoted to COMBINATIONS.md: {N}
• Failed combinations logged: {N}

🔥 TOP PROVEN COMBINATIONS
1. {name} — {skill-A + skill-B} — confidence: {low|medium|high} — ROI: {N}x — {N} uses
(or: "No proven combinations yet — accumulating data")

💡 NEW SKILL PROPOSALS
• {skill name}: {capability gap it would fill}
(or: "No proposals this week")

📝 AGENTS.MD UPDATE PROPOSALS
• {proposed addition} — operator decides whether to apply
(or: "No updates proposed this week")

📈 ECOSYSTEM HEALTH
• COMBINATIONS.md entries: {total} — Experimental: {N} | Proven: {N} | Deprecated: {N}
• .learnings pending review: {N} | Resolved this week: {N}

⏰ Next distillation: Sunday {date}
```

---

# End of SKILL.md