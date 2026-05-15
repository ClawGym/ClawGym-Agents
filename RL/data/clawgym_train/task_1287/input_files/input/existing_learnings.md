# LEARNINGS (Excerpt)

## [LRN-20260329-0A1] best_practice

**Logged**: 2026-03-29T14:42:10Z
**Priority**: medium
**Status**: pending
**Area**: config

### Summary
Use pnpm workspaces; avoid npm to prevent lockfile conflicts

### Details
The repository is configured for pnpm workspaces (pnpm-lock.yaml present). Running `npm install` created `package-lock.json` and resulted in dependency resolution mismatches across packages.

### Suggested Action
- Remove `package-lock.json`
- Run `pnpm install` at the workspace root
- Document the requirement in CLAUDE.md and AGENTS.md

### Metadata
- Source: conversation
- Related Files: package.json, pnpm-lock.yaml
- Tags: build, dependencies, workspace
- Pattern-Key: build.package_manager.pnpm
- Recurrence-Count: 2
- First-Seen: 2026-03-20
- Last-Seen: 2026-03-29

---

## [LRN-20260405-7FQ] best_practice

**Logged**: 2026-04-05T09:11:03Z
**Priority**: low
**Status**: pending
**Area**: agents

### Summary
Avoid dumping tool debugging output directly into chat

### Details
Status lines like "🛠️ Exec: ..." and raw tool output flooded the conversation and caused rate limiting. This reduces clarity for the user and clutters the transcript.

### Suggested Action
- Keep tool output in logs unless user explicitly requests it
- Summarize outcomes in 1–2 lines in chat
- Add a guard to redact verbose logs by default

### Metadata
- Source: simplify-and-harden
- Related Files: agents/transport.py
- Tags: ux, messaging
- Pattern-Key: comm.tool_output.noise_reduction
- Recurrence-Count: 1
- First-Seen: 2026-04-04
- Last-Seen: 2026-04-05

---