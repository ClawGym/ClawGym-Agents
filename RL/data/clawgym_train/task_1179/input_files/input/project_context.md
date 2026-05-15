# Project Context

- Repository: JavaScript/TypeScript monorepo for a web service and CLI tools.
- Package manager: pnpm (workspaces enabled).
- Node version: 20.x (LTS). CI uses Node 20.
- Lockfile: pnpm-lock.yaml (committed).
- Workspace files: pnpm-workspace.yaml at repo root; packages/* for subprojects.
- CI install step: pnpm install --frozen-lockfile
- Convention: Do not run npm install in this repo; always use pnpm.
- Additional notes:
  - package.json includes "packageManager": "pnpm@9.x"
  - Scripts assume pnpm (e.g., pnpm test, pnpm build)