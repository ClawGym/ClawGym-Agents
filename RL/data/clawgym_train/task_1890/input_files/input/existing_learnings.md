## [LRN-20250110-001] correction

Logged: 2025-01-10T09:05:00Z
Summary: Team standardizes on pnpm instead of npm; lock file is pnpm-lock.yaml
Details: Multiple CI failures occurred when contributors ran npm install. The repository uses pnpm workspaces and pnpm-lock.yaml. Commands and docs should use pnpm exclusively.
Suggested Action: Update READMEs and scripts to use pnpm; add a preflight check that warns if npm is used.
Tags: package-manager, pnpm, setup