# Form Performance and Conversion

Core guidelines
- Fewer fields almost always convert better; target 3–5 fields on the first step.
- Load time over 2s on mobile increases abandonment.
- Inline, real-time validation beats error pages.
- Pre-fill when you can; never ask for the same data twice.
- Use sensible defaults and defer choices that can be inferred later.
- Chunk long forms into short, predictable steps with a progress indicator.
- Avoid dropdowns for small sets; use radio buttons or chips for faster selection.
- Optimize mobile: numeric keypad for numbers, email keyboard for email.
- Defer account verification (email/SMS) until after the first value moment if risk allows.
- Save partial progress automatically and restore on return.

Micro-interactions
- Validate on blur; show clear errors without aggressive blocking.
- Use optimistic UI for optional fields to keep momentum.
- Keep CTAs consistent and obvious; avoid multiple primary actions.

Ordering and grouping
- Put the most critical fields first; remove anything that does not change the first session.
- Group related fields and eliminate redundant captures across steps.
- Ask only one optional question per step to keep cognitive load low.

Content and clarity
- Replace jargon with plain language labels.
- Add brief helper text where confusion is likely.
- Use examples to guide format (e.g., “Acme Inc”, “10–25 people”).

Timing
- Prompt after success states rather than before critical actions.
- Avoid mid-task interruptions; use end-of-flow or next-session prompts.

Metrics
- Track impression → interaction → completion funnels for each step.
- Measure time-to-complete and drop-off per field to find hotspots.
- A/B test field removal or deferral before adding new questions.