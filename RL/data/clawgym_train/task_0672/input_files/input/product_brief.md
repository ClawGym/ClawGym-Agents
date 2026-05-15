# Team Calendar Digest — Product Brief

Summary
The Team Calendar Digest gives every teammate a clear view of the week ahead. It gathers the most important meetings, time‑off, and team ceremonies into a single weekly email and a compact Slack post, tailored to each person’s time zone. The goal: fewer surprises, fewer conflicts, and more time for focused work.

Background
We are a remote‑first company with teams spread across AMER, EMEA, and APAC. People routinely miss changes to recurring meetings, get surprised by overlapping events, or discover time‑off too late to plan around it. Currently, teammates must juggle multiple calendars, HR tools, and Slack channels to piece together the week.

Primary Users
- Managers planning team priorities and coverage
- ICs planning deep‑work blocks and avoiding conflicts
- Operations and coordinators who need visibility into ceremonies and time‑off
- New hires who need orientation to team rhythms

Jobs To Be Done
- When my week begins, I want a simple summary of my team’s upcoming events so I can plan my focus time and avoid conflicts.
- When my team’s schedule shifts, I want to know the changes before the week starts so I can adjust plans and communicate early.
- When a teammate is off, I want to see coverage gaps without digging through HR and shared calendars.

Scope (MVP)
- Weekly digest email sent Monday 07:00 local time for each recipient.
- Optional Slack summary posted to a chosen team channel by 08:00 recipient’s local time.
- Content includes (high‑signal only):
  - Team ceremonies (standups, planning, retro, all‑hands)
  - 1:1s (only if marked team‑visible or if the recipient is a participant)
  - Time‑off and company holidays (from HR system)
  - Conflicts and overloaded day alerts (≥3 meetings overlapping or >6 hours scheduled)
- Time zones normalized to the recipient’s locale; meeting times shown in recipient’s local time with source TZ note.
- Links back to source calendar event.
- Light grouping by day with human‑readable summaries (e.g., “Mon: 10–12 standups, 1:1s; Wed overloaded, consider moving backlog grooming”).
- Per‑user preferences:
  - Email on/off (default: on)
  - Slack summary on/off (default: off for MVP)
  - Include 1:1s: on/off (default: off unless they are the participant)
- Delivery performance target: all digests delivered within a 15‑minute window per timezone cohort.

Out of Scope (MVP)
- Real‑time alerts or day‑of pings
- Calendar editing, rescheduling, or RSVP from the digest
- Cross‑company calendar visibility
- Mobile app or push notifications

Integrations
- Google Calendar (service account with domain‑wide delegation)
- Microsoft 365 (Graph API) — post‑MVP, behind a feature flag
- HRIS (BambooHR) for time‑off and holidays
- Email: Amazon SES or SendGrid (choose one for MVP)
- Slack: Incoming webhook or bot token with chat:write to target channel

Privacy & Data Handling
- Respect calendar visibility:
  - Only events marked public or team‑visible are included
  - Private event titles are obscured as “Busy”
- Only show 1:1s to the two participants or if explicitly team‑visible
- Data retention: store event metadata needed for digest generation for ≤14 days
- Avoid persisting event bodies or attendee notes; store minimal fields (id, start/end, visibility flag, organizer, attendees hash)
- SOC 2 controls: log access to calendar scopes; rotate credentials every 90 days

Constraints & Assumptions
- Must scale to 500+ users across 50+ teams without exceeding API rate limits
- Daylight Saving Time and locale formatting handled correctly
- Retry strategy for email/Slack delivery with idempotency keys to prevent duplicates
- Digest size budget: keep email under 150KB to avoid clipping in common clients
- Accessibility: AA contrast, semantic headings, and alt text for icons

Success Metrics (North Star + leading indicators)
- ≥60% weekly digest open rate within 48 hours
- ≥15% click‑through to at least one event link
- 20% reduction in overlapping meeting conflicts week‑over‑week for pilot teams
- Slack post engagement (reactions or thread replies) ≥25% of members
- Unsubscribe/opt‑out rate ≤5% after 4 weeks

Key Risks
- Calendar scopes too broad may raise privacy concerns
- Time zone normalization errors erode trust
- Over‑notification fatigue leads to opt‑outs
- Outlook (Graph) parity gaps delay multi‑calendar support
- HRIS API limits or delays cause stale time‑off data

Rollout Plan
- Phase 0: Internal team (Eng + Design) — 2 weeks
- Phase 1: Managers in Product & Eng (50 users) — 3 weeks, collect feedback
- Phase 2: Opt‑in for all departments
- Phase 3: Default‑on for all teams, with clear opt‑out

Operational Considerations
- Monitoring: delivery rate, bounce rate, Slack API errors
- On‑call: weekday morning coverage by Platform team for first 4 weeks
- Feature flag: workspace‑level and user‑level toggles

Email & Slack Content Guidelines
- Plain, scannable layout with day sections
- Clear labels: “Overloaded day”, “Potential conflict”
- Action links: “Open in Calendar”, “Manage preferences”
- Slack: concise summary with a link to full email or web view

Open Questions
- Definition of “team”: reporting line, project membership, or Slack channel membership?
- Should RSVP status be shown for Outlook if we only have organizer’s visibility?
- Default Slack summary: off for all or on for pilot teams only?
- Are ICS attachments required for MVP or later?
- Should private “Working session” events be included as “Busy” to signal load?

Appendix: Field Inventory (MVP)
- Event: id, start, end, summary, visibility, organizer, attendees (role + hashed email), hangoutLink or conferenceUrl, source calendar
- Time‑off: employee id, start, end, type (OOO, vacation), public visibility flag
- User prefs: email_on (bool), slack_on (bool), include_1_1 (bool), timezone

Source of truth: product strategy review 2026‑Q2 and stakeholder interviews (Ops, Eng, Design).