# Contributing to OpenClaw

Welcome, and thank you for considering a contribution to OpenClaw. This document is the source of truth for contribution norms. Please read it before opening a pull request.

## Scope and discussion

- Small, focused bugfixes and documentation fixes: open a PR directly.
- New features, large refactors, or architecture changes: start a GitHub Discussion or ask in Discord first.
- Keep one logical change per PR. Do not mix feature work, refactors, and docs in the same PR.

## Before you start

- Inspect nearby implementation and tests in the area you plan to change.
- Search for existing work in `upstream/*` branches and open PRs to avoid duplicating effort.
- Prefer source-level fixes over patching built artifacts.

## Validation expectations

Unless your change is docs-only, run the core checks locally before opening your PR:

- `pnpm build`
- `pnpm check`
- `pnpm test`

Subsystem-specific checks should also be run when relevant:

- Gateway/auth/channels changes: `pnpm test:gateway`
- UI/web changes: `pnpm test:ui`
- Extensions: `pnpm test:extensions` (and closed-loop tests where applicable)
- iOS/macOS: `pnpm ios:gen && pnpm ios:build`
- Android: `pnpm android:lint && pnpm android:test`

Docs-only changes can usually skip full build/test and instead run:

- `pnpm format:docs:check`
- `pnpm lint:docs`
- `pnpm docs:check-links` (when link checks are enabled in CI)

Tip: If available, use the repo helper to derive a validation plan from your diff.

## Tests and regressions

- Add or update regression tests with your fix when practical.
- Keep tests close to the changed code (follow existing patterns).
- For bugfixes, include a test that would have failed before your patch.

## PR preparation

Every PR should include:

- A clear title that indicates scope and subsystem.
- An explanation of what changed and why.
- The validation steps you ran (commands and scope).
- Screenshots or recordings for UI/visual changes (before/after).
- Any risk areas and how you mitigated them.
- If the PR is a follow-up to existing work, include links.

## AI-assisted work

- Mark AI-assisted work in the PR title or description (e.g., “[AI-assisted] …”).
- State testing level: untested / lightly tested / fully tested.
- You are responsible for understanding and reviewing all submitted code.
- Include prompts or session notes when they help maintainers review faster.

## Style notes

- Follow existing code style and patterns in the touched area.
- Control UI uses Lit with legacy decorators; keep reactive fields in legacy style:
  - `@state() foo = "bar";`
  - `@property({ type: Number }) count = 0;`
- Do not switch decorator styles unless the UI build tooling is intentionally being changed too.

## Security/auth changes

- Keep scope tight and explain impact and risk clearly.
- Call out any configuration or migration steps for operators.
- Include rollback notes when applicable.

## Maintainer routing hints (not strict)

- Peter Steinberger — overall maintainer / repo direction
- Shadow — Discord, ClawHub, moderation
- Vignesh — Memory (QMD), formal modeling, TUI, IRC
- Jos / Ayaan — Telegram
- Tyler Yust — agents, subagents, cron, BlueBubbles, macOS app
- Mariano Belinky / Vincent Koc / Josh Avant — security/auth/core hardening
- Val Alexander — UI/UX, docs, agent dev experience
- Gustavo Madeira Santana — agents, CLI, web UI
- Jonathan Taylor — ACP subsystem, gateway features/bugs, Gog/Mog/Sog CLI’s

## Checklist before opening a PR

- [ ] One logical change per PR
- [ ] Nearby code and tests reviewed
- [ ] Appropriate validation commands run locally
- [ ] Regression tests added/updated (when practical)
- [ ] AI assistance disclosure and testing level included
- [ ] Screenshots for UI changes (if applicable)
- [ ] CI expected to pass

Thank you for helping improve OpenClaw!