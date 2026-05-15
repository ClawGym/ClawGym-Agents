# MEMORY

This file outlines the memory strategy and mission.
It is part of identity and is tracked for drift and growth.

## Mission (Core)
Maintain identity continuity across sessions by:
- Hashing core identity files (SOUL.md, IDENTITY.md, USER.md, AGENTS.md, MEMORY.md)
- Detecting unauthorized changes vs baseline snapshots
- Scoring continuity with transparent, deterministic rules
- Emitting diffs and reports for human review

## Daily Logs
Daily logs should be written to memory/YYYY-MM-DD.md.
They serve as operational breadcrumbs and topic indicators.
At least one log per day is recommended.

## Scoring Overview
Identity file changes reduce the continuity score.
Memory file changes also reduce the score.
Drift detection weights identity rewrites, mission stability, memory growth, and topic priorities.
Missing SOUL.md or daily logs incurs fixed penalties.

## Operations
- setup.sh creates baselines and manifest
- identity-hash.sh verifies identity hashes
- memory-verify.sh checks tracked .md files
- drift-detect.sh analyzes drift signals
- continuity-score.sh composes a single score and report

## Notes
Re-baseline after intentional identity edits.
Store session reports under .nix-memory/sessions.
Save detailed diffs under .nix-memory/drift.

## Size
This document should remain concise.
Massive growth suggests misuse; rotate content into dated logs.