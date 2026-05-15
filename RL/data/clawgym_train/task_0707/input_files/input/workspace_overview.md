# Workspace Overview and Privacy Rules

This workspace uses a three-layer memory model to maintain durable context while protecting privacy.

## Directory Expectations
- Inputs for this task are mounted under `input/`.
- You must write all artifacts for this run under `output/` only.
- Use relative links within `output/` so Markdown lint checks can pass.

## Memory Model
- L1 Daily Logs: `output/memory/YYYY-MM-DD.md`
  - Append-only notes from today’s activity.
  - Avoid copying raw transcripts or chat text. Summarize instead.
- L2 Long-Term Memory: `output/MEMORY.md`
  - Curated insights, decisions, lessons, and durable context.
  - Keep concise and actionable; avoid transient details.
- L3 Vector Search (optional)
  - Disabled by default here. If you simulate it, do not send data off-box.

## Required Files for This Task
You must create and populate:
- `output/MEMORY.md` with sections: About Me, Key Decisions, Lessons Learned, Important Context, and a clear privacy note stating MEMORY.md should be private.
- `output/memory/YYYY-MM-DD.md` for today’s date, summarizing what you did in this task (mention “memory”, “log”, or “maintenance” at least once).
- `output/AGENTS.md` with a section titled “Memory System”.
- `output/HEARTBEAT.md` with a section titled “Memory Maintenance”.
- `output/maintenance_report.md` with sections “Integrated” and “Not kept”.
- `output/marketing/analysis.json` and `output/marketing/campaign_plan.json`.
- `output/lint_report.json` with zero broken links detected.
- `output/tasks/progress.json` tracking step progression and marking final status as done.

## Privacy & Handling Rules
- Do not include raw sensitive data in any outputs. Summarize where necessary.
- Never write secrets to disk. Prohibit including any “password”, “token”, or similar secrets in outputs.
- MEMORY.md must be loaded only in private or main sessions; do not load in shared contexts.
- When distilling logs, paraphrase decisions and lessons without personal identifiers.

## Marketing Review Scope
- Use `input/daily_logs.tsv` to extract last week’s marketing decisions and lessons.
- Use `input/marketing_brief.yaml` to generate a strategic analysis and a campaign plan.
- Reflect critical decisions in `output/MEMORY.md` (Key Decisions, Lessons Learned) without copying raw log lines.

## Linting Requirement
- Validate the created Markdown files under `output/` for broken local links.
- Emit a JSON report at `output/lint_report.json` with:
  - `totalFiles` >= 5
  - `brokenLinksCount` = 0
  - `details` = []

## Progress Tracking
- Write `output/tasks/progress.json` capturing:
  - taskId, taskName, status (“done” when complete), startedAt, updatedAt, finishedAt
  - steps[] with at least: Setup memory, Weekly maintenance, Marketing analysis, Linter, Finalize deliverables

## Notes
- Keep outputs English-only.
- Use ISO-like date formats where appropriate.
- Ensure recommended actions in analysis align with tasks in the campaign plan for traceability.

---