# Internal Tooling Initiative — Multi-Agent Starter Kit

## Overview
We are a small internal team building a lightweight, multi-agent starter kit to accelerate engineering tasks (e.g., documentation, verification checks, and simple workflow automation). The first deliverable is a portable, text-first governance and architecture framework that can run locally without special infrastructure.

## Team & Constraints
- Team size: 3–5 engineers (mix of backend and tooling experience)
- Timeline: Initial starter kit within 1–2 weeks
- Environments: macOS, Linux, Windows (must be cross-platform)
- Network: Prefer offline/air-gapped operation; no external API dependencies required
- Tooling: Python 3 available; Git available; shell may vary (PowerShell, bash/zsh). Favor Python one-liners for cross-platform checks.
- Storage: Filesystem only (text-based). Avoid absolute paths; use relative paths under ./output/ for generated artifacts.

## Goals
1. Governance: Provide WAL (write-ahead logging), VBR (verification checks), ADL baseline (persona alignment), VFM (cost/value thinking), and IKL (infrastructure knowledge logging) in a portable, file-based way.
2. Architecture: Choose a pragmatic architecture that fits a small team and enables quick iteration without over-engineering.
3. Velocity: Define a short playbook (8–12 practices) that materially increases delivery speed.
4. Autonomy: Document how memory persists across sessions, how identity is represented, and how a simple heartbeat runs without external services.

## Non-Functional Requirements
- Portability: All scripts and checks must work cross-platform.
- Simplicity: Prefer a modular monolith or process-per-tool approach rather than microservices.
- Observability: Text logs and JSONL for governance artifacts; clear status indicators.
- Cost Awareness: Encourage tracking tokens/costs even when hypothetical; keep expenses low.
- Security: No secrets in the repository; no tokens in logs; redact sensitive info by design.

## Scope
- In-scope:
  - Text-based governance artifacts under ./output/governance/
  - Architecture documents under ./output/architecture/
  - Velocity playbook under ./output/velocity/
  - Autonomy runbook under ./output/autonomy/
  - TOOLS.md under ./output/memory/ for infrastructure facts (no secrets)
- Out-of-scope:
  - Cloud provisioning, containers, or orchestration
  - External service dependencies
  - Complex CI setup (can be suggested, not implemented)

## Architectural Direction (Guidance)
- Likely Approach: Modular monolith (single repo) with small, composable Python scripts for governance tasks and documentation generation.
- Process Model: Each capability (WAL, VBR, ADL baseline computation, VFM aggregation) can be a standalone script invoked on demand.
- Data Model: Append-only JSONL for logs; small JSON/Markdown for reports; relative paths only.
- Directory Convention:
  - output/governance/: WAL.jsonl, VBR_checks.json, ADL_baseline.json, VFM_report.json
  - output/architecture/: ADR-001.md, high_level_architecture.md
  - output/velocity/: 10x_playbook.md
  - output/autonomy/: runbook.md
  - output/memory/: TOOLS.md

## Verification Expectations
- Cross-platform checks should avoid shell-specific features:
  - Prefer: python -c "import os,sys; sys.exit(0 if os.path.exists('output/architecture/ADR-001.md') else 1)"
  - If a shell check is used, provide a Python fallback or ensure it works in sh-compatible shells.
- VBR must include:
  - file_exists check for output/architecture/ADR-001.md
  - at least one portable command check (Python one-liner)
  - optional file_changed or git_pushed checks (simulate locally)

## Governance Triggers
- WAL: Before responding to user corrections or making key decisions; on state changes (e.g., “architecture baseline chosen”).
- VBR: Before claiming “done,” verify files exist and portable commands succeed.
- ADL: Analyze sample responses for anti-patterns (sycophancy, passivity, hedging, verbosity) and persona signals (direct, opinionated, action-oriented).
- VFM: Maintain small hypothetical cost entries and produce suggestions to keep value high and cost low.
- IKL: Capture environment facts (ports, paths, local services) in TOOLS.md; never include secrets.

## Acceptance Criteria (for this starter)
- All required files under ./output/ exist and are coherent.
- No absolute paths; everything uses relative paths.
- Checks are runnable cross-platform.
- Documentation is concise and actionable for a small team.

---