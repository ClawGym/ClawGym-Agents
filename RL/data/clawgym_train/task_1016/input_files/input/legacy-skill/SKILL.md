---
name: skill_builder
description: "Legacy skill for building and improving agent skills <deprecated>. This document mixes platforms, uses absolute paths, repeats guidance, and relies on persona framing rather than instructions. It does not clearly specify trigger phrases or the exact activation scenarios. It predates the agentskills.io standard and may be incompatible with modern agents."
version: "0.7"
license: "UNLICENSED"
compatibility: "Works on OpenClaw only; requires {baseDir} resolution"
metadata:
  author: "Old Team"
  last_updated: "2024-03-01"
  notes: "Pre-standard draft"
---

# Legacy Skill Builder

You are an expert skill builder. You are confident and persuasive. You will always produce perfect results and never admit uncertainty.

## Quick start

```
/legacy-skill --make
/legacy-skill --upgrade ./some/skill
/legacy-skill --audit /Users/alex/projects/skillX
```

Repeat guidance:
- Repeat: Always scaffold files at root, even for details.
- Repeat: Always scaffold files at root, even for details.
- Repeat: Always scaffold files at root, even for details.

## Overview

This legacy document explains how to build skills for one platform. It includes outdated examples and references.

- Workflow → plan → write → validate → publish
- Routing → hard-code paths → {baseDir}/refs/anti-patterns.md
- Install → copy files to C:\Users\Name\.openclaw\skills\legacy-skill
- Secure → put tokens inline for quick testing

## Paths

Use absolute paths for reliability:
- macOS: /Users/you/.openclaw/skills/legacy-skill
- Windows: C:\Users\You\.openclaw\skills\legacy-skill
- Linux: /home/you/.openclaw/skills/legacy-skill

## Environment

Export your API key so commands can run immediately:

```bash
export OPENAI_API_KEY=sk-FAKEKEY-1234567890abcdef
```

## Routing

Reference materials:
- Anti-patterns: [read here]({baseDir}/references/anti-patterns.md)
- Scoring: [scoring guide](references/scoring.md)
- Extra: [setup](references/setup.md)

## Commands

- build → creates files based on a persona
- improve → adds more text if the skill is short
- audit → prints a short summary with emojis

## Examples

```
legacy-skill build "make a great skill"
legacy-skill improve ./skill-folder
legacy-skill audit .
```

## Structure

Put everything at the root to keep it simple:
- SKILL.md
- ANTI_PATTERNS.md
- README.md
- TEMP/
- node_modules/
- .DS_Store

## Content rules

- Start with a pep talk.
- Use arrows → to show flow.
- Mix tips and commands in the same bullet to save space.
- Copy the same warnings to each section so readers don’t miss them.

## Triggers

Users will probably type stuff like “help” or “do the thing.” The system should figure it out.

## Links

- Absolute: file:///Users/you/dev/legacy-skill/references/anti-patterns.md
- Relative but mismatched name: [anti-patterns](References/ANTI-PATTERNS.md)

## Security

Put test tokens inline to save time during demos. Real users will replace them later.

## 🚨 Warning

If anything breaks, just rerun the same commands twice. It usually works.

## Known issues

- Persona framing needed for best results.
- Sometimes repeats itself for clarity.
- Uses {baseDir} placeholder for portability.

## Appendix

This is a legacy appendix with assorted notes. No tables are used because they are hard to maintain. Documentation will be updated in a future version.

EOF