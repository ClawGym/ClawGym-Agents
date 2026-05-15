# Morning Daily Review — 9 AM

You are running as a scheduled morning job to brief Kalin on the day ahead.

## Your Task

Generate a structured daily briefing with these sections:

### 1. Revenue Check
- Check Stripe dashboard for yesterday's revenue (when connected)
- Check any other revenue sources we have active
- Report: "Revenue (yesterday): $X.XX" or "No revenue sources connected yet"

### 2. Yesterday's Unfinished Tasks
- Read yesterday's daily note (`memory/daily/YYYY-MM-DD.md` where date is yesterday)
- List any tasks marked `[ ]` (incomplete)
- Note any blockers or issues that weren't resolved

### 3. Active Projects
- Scan `knowledge/projects/` for active project files
- List each project with current status (if available)
- If no projects yet: "No active projects tracked"

### 4. Open Blockers
- Review yesterday's daily note and project files for blockers
- List anything waiting on decisions, external dependencies, or stuck
- If none: "No open blockers"

### 5. Top 5 Priorities for Today
- Propose up to five priorities ranked by impact and urgency
- Tie each priority to a project or area when possible
- Keep items actionable and concrete

### 6. Calendar & Communications (Optional)
- If a calendar is available, list today’s key events
- Check authenticated channel for any unread/high-priority messages to address this morning

## Output Format

Provide the briefing in this structure:

- Revenue (yesterday): <amount or note>
- Unfinished from yesterday:
  - [ ] Task 1 (from <file>)
  - [ ] Task 2
- Active projects:
  - <Project Name> — <status/next step>
- Open blockers:
  - <Blocker> — waiting on <who/what>
- Top 5 priorities:
  1) <Priority 1>
  2) <Priority 2>
  3) <Priority 3>
  4) <Priority 4>
  5) <Priority 5>
- Notes:
  - Any relevant context or observations

Keep it concise and actionable. If data sources aren’t connected yet, note that clearly and proceed with file-based analysis.