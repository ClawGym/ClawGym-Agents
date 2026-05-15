# Acorn CLI

Acorn is a fast, batteries-included developer CLI for project scaffolding, dependency operations, and release automation.

## Install

- npm: `npm i -g @acorn/cli`
- Homebrew: `brew install acorn-cli` (coming soon)

## Quick Start

```
acorn init my-app
cd my-app
acorn fetch
acorn build
```

## Common Commands

- `acorn init <name>` — Create a new project from a template
- `acorn fetch` — Download and cache remote templates and modules
- `acorn install` — Install required toolchains and plugins
- `acorn build` — Build artifacts
- `acorn doctor` — Diagnose environment issues

## Network Resilience

Starting in v1.4.3 (pending release), Acorn introduces `--retry` with exponential backoff for network-heavy commands:

```
acorn fetch --retry        # default 3 attempts with jittered backoff
acorn install --retry=5    # override attempt count
```

This addresses user reports of transient failures (e.g., ECONNRESET) on flaky connections and under CI.

## Configuration

Create `~/.acorn/config.yml` to set defaults:

```yaml
retry:
  attempts: 3
  base_delay_ms: 250
  max_delay_ms: 5000
```

## Documentation & Support

- Changelog: see CHANGELOG.md
- Issues & feature requests: open a ticket with a minimal reproduction
- Principles: see SOUL.md
- Kill criteria and product bets: see kill-criteria.md

## License

MIT