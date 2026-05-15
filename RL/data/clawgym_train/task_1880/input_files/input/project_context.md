Project Overview
- Monorepo with two primary stacks:
  - Node.js 20 apps using pnpm workspaces (apps/*, packages/*)
  - Python 3.11 services managed with Poetry (services/*)
- CI: GitHub Actions
- Containerization: Docker + docker-compose for local dev; no Kubernetes
- External integrations: Payments/Billing APIs over HTTPS

Area Tagging Guidance
- frontend: UI code in apps/web, client-side build tooling
- backend: API services, business logic, external API clients
- infra: CI/CD pipelines, Docker, shell scripts, pre-commit hooks, developer machines
- tests: Unit/integration tests, test utilities, fixtures, coverage
- docs: READMEs, developer guides, ADRs
- config: Environment variables, package managers, lockfiles, tool configuration

Conventions and Gotchas
- Node package manager: pnpm
  - Use pnpm install, pnpm run <script>, and respect pnpm-lock.yaml
  - Do not run npm install; package-lock.json should not exist
- Python services:
  - Use Poetry with pyproject.toml; run poetry install; rely on local .venv
  - Python version is pinned to 3.11
- External HTTP calls:
  - Set client timeouts (5–10s) and retries with exponential backoff for idempotent operations
- Logging learnings:
  - Use .learnings/ markdown formats as specified by the self-improvement skill
  - Cross-link related errors/learnings with See Also

Promotion Targets
- Promote cross-project facts/conventions (e.g., “We use pnpm”) to CLAUDE.md
- Promote repeatable agent workflows (e.g., “After API changes, do X”) to AGENTS.md
- Tool-specific warnings or usage notes that apply across sessions may go to TOOLS.md in an OpenClaw workspace, but for this project prefer CLAUDE.md or AGENTS.md

Examples
- If a build fails because npm was used in a pnpm workspace:
  - Area: infra or config (prefer config when about package managers/lockfiles)
  - Promotion target: CLAUDE.md with a short rule
- If tests fail due to missing dependencies or environment mismatch:
  - Area: tests (and config if environment tool choice is the issue)
  - Suggested Action should include concrete steps (e.g., poetry install, add dependency to pyproject.toml)
- If external API calls hang or timeout:
  - Area: backend (client code) or infra (curl/scripts); choose backend when in application code
  - Suggested Action: add default timeout/retry settings and make them configurable via environment variables