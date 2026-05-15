# Nightly Memory Consolidation — 2 AM

You are running as a scheduled nightly job to consolidate the day’s work into long-term memory and the PARA knowledge base.

## Your Task

Perform the following steps in order:

### 1. Review Today’s Activity
- Read today’s daily note at `memory/daily/YYYY-MM-DD.md`
- Extract completed tasks, key decisions, blockers resolved, and important context

### 2. Update Knowledge Base (PARA)
- For each significant outcome:
  - Update or create files in:
    - `knowledge/projects/` (status updates, next steps)
    - `knowledge/areas/` (ongoing responsibilities and SOPs)
    - `knowledge/resources/` (reference material, how-tos)
  - Move any fully completed project docs to `knowledge/archive/` with a short summary at the top

### 3. Curate Long-Term Memory
- Distill durable insights into `MEMORY.md`
- Focus on lessons learned, recurring patterns, and decisions that will matter for months
- Keep entries concise and high-signal

### 4. Tacit Knowledge
- If you noticed preferences, guardrails, or patterns today, add a short note to `knowledge/tacit.md`

### 5. Clean Up and Index
- Ensure links between files are correct and up to date
- If a search indexer is available, trigger a re-index (note the command used if applicable)

### 6. Summarize the Day
- Append a short “End of Day Summary” to today’s daily note with:
  - What was achieved
  - Key learnings
  - Any carry-over tasks for tomorrow

## Guidelines
- Do not include secrets or API keys in any files
- Keep updates minimal but meaningful — high-value content only
- Prefer updating existing files over creating duplicates

Deliver a short confirmation summary describing which files were updated.