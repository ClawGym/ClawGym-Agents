# Intent: Meeting Notes Summarization Skill

Goal
Transform messy, unstructured meeting notes into a clean, structured summary capturing:
- Key decisions with rationale (if stated)
- Action items with owner, task, due date, and status
- Risks/assumptions/dependencies
- Parking lot / follow-ups
- Next meeting details (if mentioned)
- Lightly normalized meeting metadata (title/topic, date/time, participants)

When this skill should trigger
- Any time the user shares raw notes, call transcripts, or bullet dumps from a meeting and asks for a summary or action items.
- Phrases like “turn these notes into something useful”, “please summarize this meeting”, “extract action items”, “clean up my notes”.
- Should still trigger even if the user doesn’t explicitly say “meeting” (e.g., “these are from today’s sync” or “transcript from the Zoom call”).
- Should trigger even if the notes are inconsistent, partially timestamped, or contain small typos.

Success criteria
- Output is concise, consistent, and scannable by an executive: 1–2 screenfuls for most meetings.
- All action items include: owner (or “TBD”), task description, due date (YYYY-MM-DD if any date is present or inferable), and status (“open” by default).
- Decisions are clearly listed (not buried in prose).
- Dates normalized to ISO (YYYY-MM-DD). If a relative date is given (e.g., “by Friday”), infer the concrete date using the meeting date if available; otherwise, retain the relative phrase and flag “needs date clarification”.
- Participants and meeting date are captured if present; otherwise, omit or mark as “unknown”.
- Remove duplicates and collapse similar items; resolve pronouns when possible (e.g., “she” → specific participant if context provides).
- Preserve important qualifiers and constraints (e.g., “dependent on vendor fix”).
- Avoid hallucinating facts. If ambiguous, note the ambiguity.

Output format (default)
- Primary deliverable: Markdown report with the following sections:
  - Title (include meeting name or topic if known)
  - Meeting metadata: date (YYYY-MM-DD), participants (comma-separated), source (e.g., transcript)
  - Executive summary: 3–5 bullet points
  - Key decisions: bullets with concise phrasing and any rationale
  - Action items: a table with columns [ID, Owner, Task, Due Date, Status]
  - Risks/Dependencies
  - Parking lot
  - Next meeting (date/time if available)
- Secondary deliverable (when writing files): A machine-readable JSON file named action_items.json with an array of action items using:
  {
    "id": "AI-001",
    "owner": "Name or 'TBD'",
    "task": "short description",
    "due_date": "YYYY-MM-DD or null",
    "status": "open|blocked|closed",
    "notes": "optional context"
  }

Edge cases and normalization rules
- Multiple or inconsistent dates: prefer the date most directly tied to the meeting context near the start of the notes; otherwise, list as “unknown”.
- Relative due dates:
  - If meeting date is specified (e.g., 2025-05-06) and an item says “by Friday”, compute the ISO date relative to that week.
  - If no meeting date is known, keep “by Friday” and set due_date to null with notes: “relative date; meeting date not known”.
- Owners:
  - Map first names consistently (if a full name list is present, use those).
  - If owner is unclear (e.g., “someone needs to…”), set owner to “TBD” and add a note.
- Decisions vs. ideas:
  - Treat statements with strong verbs (approve, decide, agree, will, deprecate, pilot, commit) as decisions.
  - Treat tentative/conditional language (discuss, consider, maybe) as non-decisions unless explicitly resolved.

Examples in samples
- Expect messy bullets, timestamps, offhand comments, and inconsistent formatting.
- Expect due dates stated as “EOD Wed”, “Fri 5/10”, “by tomorrow”, or “next Mon”.
- Expect context like project names (“Atlas”, “Northstar”), team names, and vendor mentions.

Non-goals
- Don’t produce verbatim transcripts or lengthy minutes.
- Don’t fabricate owners or dates; surface ambiguities explicitly.

Quality bar
- The final Markdown is well-structured and readable without the original notes.
- Action items table is complete and accurate based on the notes.
- JSON is valid and aligns with the Markdown action items.

Optional behaviors
- If multiple meetings are concatenated, split summaries by detectable headers or date/timestamp breaks.
- If the user asks for a custom format, adapt while preserving completeness.