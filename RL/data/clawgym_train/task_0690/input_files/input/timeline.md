# Project Chronology — Phoenix Release

This document captures the draft sequence of events for the Phoenix release. Multiple system resets and conflicting notes have introduced drift; we record concrete receipts where available and flag suspected distortions for later verification.

## 2026-01-15 — Phoenix planning kickoff
- Agenda captured in “Phoenix_KO_Minutes.md” (internal note).
- Milestone framework agreed: Beta → RC1 → RC2 → Launch.
- Initial risk register opened (ID: PHX-RISK-0001 … PHX-RISK-0010).

## 2026-01-28 — Scope lock
- Scope freeze announced for non-critical features.
- Exceptions logged via Change Control Board (CCB-Records 2026-01-28.csv).
- Receipt: Draft release notes v0.9 prepared (Doc ID PHX-RN-0.9).

## 2026-02-01 — Code freeze candidate A
- Freeze window noted as 2026-02-01 00:00–2026-02-05 12:00 UTC.
- Tag created: freeze-candidate-a (commit d4c3b4a1) — recorded in release bot output.
- Artifact manifest: manifest-v0.9.8.json (sha256: e1c9f8841b8b4d3790f3c4a1a7fdc9f84837d29c7f2c5b9ab0f1ad1caa1e002a).
- CONFLICT: A secondary note (Ops log excerpt) claims freeze started 2026-02-03 09:00 UTC.

## 2026-02-05 — System reset #1
- Rollback to checkpoint CP-12 at 2026-02-05 11:00 UTC to address config drift.
- Notation: “Reset #1” indicates state divergence discovered in service mesh configs.
- Receipt: Reset summary “PHX-RESET-1.md” with before/after diffs referenced.

## 2026-02-12 — Beta build “Fermi-β2” signed
- Build ID: PHX-BETA2-FERMI (builder node: ci-04).
- Artifact: phoenix-beta2.tar.gz (sha256: b7f5c2d19e4a0a8c1d5b2a3e9f44f0cbb239ab11b8a5c0cfa4ce0e1a5b0e77dd).
- Notes: Test focus on rollback safety and dependency pinning.

## 2026-02-20 — System reset #2 (rollback to snapshot S-14)
- Rollback rationale: Divergent dependency tree detected post-beta2 hotfixing.
- Snapshot S-14 timestamp recorded as 2026-02-20 03:20 UTC.
- CONFLICT: A deployment calendar entry lists S-14 at 04:05 UTC; requires reconciliation.

## 2026-02-28 — RC1 cut (tag v1.0.0-rc1)
- Tag: v1.0.0-rc1 (commit 3f9b2c7).
- Release notes draft v1.0.0-rc1 (Doc ID PHX-RN-rc1).
- Known issue: Intermittent cache invalidation on region eu-central-1.

## 2026-03-02 — Hotfix HFX-219 applied under freeze
- Exception approved by CCB (record CCB-2026-03-02-HFX-219.csv).
- Patch commit: 7ac12fe onto RC branch (notes indicate cherry-pick from main).
- Risk: Potential delta between RC1 and RC2 branches.

## 2026-03-07 — RC2 cut (tag v1.0.0-rc2)
- Tag: v1.0.0-rc2 (commit f00ba47).
- Delta vs RC1: Includes HFX-219 and cache-invalidation fix for eu-central-1.
- Final regression suite triggered on ci-06.

## 2026-03-10 — Go/No-Go review
- Minutes record “Go” with conditions: confirm rollback time ≤ 7 minutes, verify observability baselines.
- CONFLICT: A product marketing note references a “soft go” pending partner sign-off (unclear if blocking).

## 2026-03-15 — Launch target
- Target window: 09:00–11:00 UTC.
- Comms package draft “Phoenix_Launch_Comms_v2.md”.
- CONFLICT: Marketing calendar shows a tentative public announcement on 2026-03-22, implying discrepancy between internal launch and public reveal.

## Known distortions & conflicts
- Freeze start discrepancy (2026-02-01 vs 2026-02-03).
- Snapshot S-14 timestamp discrepancy (03:20 vs 04:05 UTC on 2026-02-20).
- Go/No-Go ambiguity (full Go vs conditional/soft go).
- Public comms date misalignment (2026-03-15 internal vs 2026-03-22 public note).
- Potential branch divergence introduced by HFX-219 cherry-pick (post-RC1, pre-RC2).