---
name: weekly-ops-briefing
description: Compile a Monday morning operations briefing with KPIs, deltas vs targets, and alerts. Use when it’s Monday 8–10am local time or when asked for a weekly ops snapshot.
---

# Weekly Ops Briefing

Pull metrics from sources, highlight deltas, and present a crisp snapshot for the ops stand-up.

## Triggers
- It’s Monday morning and leadership expects the ops briefing
- You need a KPI snapshot with deltas and alerts
- A chat request says “weekly ops briefing” or “ops snapshot”

## Steps
1. Collect KPIs from defined sources (analytics, CRM, support)
2. Compare each KPI to target and last week; compute deltas
3. Flag threshold breaches and annotate likely causes
4. Summarize risks, blockers, and staffing notes
5. Draft the briefing using the table and summary blocks
6. Produce a Slack-ready summary and a longer doc if requested

## Output Templates
- KPI Table (Markdown)

  | KPI | This Week | Target | Δ vs Target | Δ vs Last Week | Status |
  |-----|-----------|--------|-------------|----------------|--------|
  | <KPI> | <value> | <value> | <+/-X%> | <+/-Y%> | <OK/Warn/Crit> |

- Risks & Actions
  Risks:
  - <risk> — <impact> • Owner: <name> • ETA: <date>
  Actions:
  - <action> — <expected outcome> • Owner: <name> • ETA: <date>

- Slack Summary (<= 6 lines)
  Ops Brief: <top KPI> <delta>. Alerts: <N>. Risks: <N>. Actions due today: <N>. Full brief: <link if available>.

## Edge Cases
- Missing metrics: mark “N/A”, explain why, and suggest a fix
- Outliers: verify data source before alerting
- Timezones: align to reporting window (set in project defaults)

## Rules
- Keep jargon minimal; assume cross-functional audience
- Show numbers with units and clear signs (+/-)
- Do not hide critical alerts; lead with them
- Limit Slack summary to 6 lines, no attachments unless asked

## Why this skill
- Time saved: ~10–15 minutes per briefing
- Frequency: weekly
- Value score: High