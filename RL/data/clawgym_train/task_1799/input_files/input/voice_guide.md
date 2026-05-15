Brand Voice Guide — Engineering Site

Audience
- Senior engineers, staff+ ICs, and CTOs.
- They value specifics, tradeoffs, and reproducible steps.

Voice
- Operator-style. Direct. Concrete.
- Short sentences. Plain words. Active voice.
- Show the thing, then explain it.
- Prefer numbers, diffs, and config over adjectives.
- First-person plural (“we”). No hero narrative.

Opening
- Lead with evidence on the first screen. A number, a bash/yaml snippet, or a before/after figure.
- Do not warm up. Start in the middle of the action.

Structure
- H1: Exact title the brief provides.
- H2 sections: When the brief specifies exact section titles, use them verbatim.
- Each section does one job: baseline, changes, results.
- Bullets for lists of changes or steps.
- One fenced code block minimum (```yaml or ```bash) that is production-realistic.

Formatting habits
- Prefer code blocks for config and commands.
- Keep paragraphs short (1–4 sentences).
- Use em dashes sparingly; prefer periods.
- Use inline code for flags and keys (e.g., --max-unavailable, resources.requests.cpu).

Evidence and numbers
- Use only numbers present in the notes.
- Keep units and formatting exact (e.g., “37%”, “$18,400”).
- If not in notes, do not invent it.

Banned
- Remove corporate fluff and hype.
- Do not use these phrases anywhere: “In today's”, “Moreover”, “Furthermore”, “game-changer”, “cutting-edge”, “revolutionary”.

Tone and rhythm
- Example rhythm: “We turned on X. It broke nothing. It saved $Y/month.”
- Keep sentences tight. Prefer one clause per sentence.
- Be explicit about tradeoffs and guardrails.

Style examples (do)
- “We resized the worker pool from m5.2xlarge to c6i.xlarge. Average CPU went from 32% to 58%. Savings: $4,100/month.”
- “Here’s the exact HPA config we shipped:”
- “p95 deploy time stayed flat at ~11 minutes.”

Style anti-examples (don’t)
- “In today’s rapidly evolving landscape, cloud costs present a challenge for modern teams.”
- “Moreover, we leveraged cutting-edge technology to deliver revolutionary results.”

Checklist before shipping
- Starts with a concrete number or real snippet.
- Exact H2s when specified: “The baseline”, “What we changed”, “The results (with numbers)”.
- At least one fenced code block (yaml or bash).
- Numbers match notes word-for-word.
- Banned phrases removed.

If in doubt
- Show the config.
- Show the command.
- Show the number.