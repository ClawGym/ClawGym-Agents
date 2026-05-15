# OpenClaw Subagents Orchestrator Setup — Requirements

Use this document to guide configuration and identity setup. All paths must be relative and live under the output/ directory.

## Configuration Goals
- Pattern: Orchestrator (depth-2 max)
- Defaults for subagents:
  - model: "anthropic/claude-haiku-4-5"
  - thinking: "basic"
  - maxSpawnDepth: 2
  - maxChildrenPerAgent: 3
  - maxConcurrent: 4
  - runTimeoutSeconds: 900
  - archiveAfterMinutes: 30
- Agents: exactly three (IDs from agents.csv): main, researcher, writer
- Workspaces: output/workspace-<id> for each agent (no absolute or home `~` paths)
- Per-agent override (main):
  - subagents.allowAgents: ["researcher", "writer"]
  - subagents.thinking: "none" (for subagents it spawns)

## Tools Policy (Subagents)
- Deny: ["gateway", "cron"]
- You may allow basic tools suitable for subagents (e.g., "read", "exec", "process", "browser") as needed.

## Identity & Memory Files (per agent)
Create under output/workspace-<id>/:
- SOUL.md
  - Must include lines:
    - "Name: <exact name from CSV>"
    - "Role: <exact role from CSV>"
- AGENTS.md
  - Must include line:
    - "Session Key: agent:<id>:main"
  - Memory instructions section must reference both "WORKING.md" and "MEMORY.md".
- HEARTBEAT.md
  - Include a checklist and the exact stand-down string: HEARTBEAT_OK
- memory/ directory with empty placeholder files:
  - memory/WORKING.md
  - memory/MEMORY.md

## Heartbeats (Staggered)
Create output/heartbeats.tsv with header:
- agent_id, cron, stagger_minute
- Use cron: "0,15,30,45 * * * *" for all
- Stagger minutes:
  - main: 0
  - researcher: 2
  - writer: 4

## sessions_spawn Plan (Example)
Create output/spawn_plan.json with:
- orchestrator_task (object):
  - Instructs acting as an "orchestrator" and to spawn "two" workers in parallel (one research, one writing)
  - model: "anthropic/claude-sonnet-4-5"
  - thinking: "basic"
  - runTimeoutSeconds: between 900 and 1800
  - mode: "run"
- worker_tasks (array of exactly two objects):
  - One research-oriented task and one writing-oriented task
  - model: "anthropic/claude-haiku-4-5"
  - thinking: "none"
  - cleanup: "delete"
  - runTimeoutSeconds: <= 600
  - Clear task strings aligned to their roles

## Path Constraints
- Do not use absolute paths (no leading "/")
- Do not use home shortcuts (no "~")
- All workspaces and references must be under output/

## Notes
- Use only the three agents defined in agents.csv.
- Identity files must reflect the exact names and roles from agents.csv.
- If any external constraints conflict with the above, prioritize the requirements in this document.