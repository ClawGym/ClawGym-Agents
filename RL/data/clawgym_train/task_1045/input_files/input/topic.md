Title: Explaining TinyLLMTrainer via a practical modify → humanize → self‑evaluate → decide loop

Audience
- Engineers who can read PyTorch and want a lean recipe for training a very small transformer locally.
- Readers who already know basic training loops and want experiments and numbers instead of generalities.

Scope and goals
- Explain the TinyLLMTrainer project (see project_readme.md) as a concrete case study of the write → de‑AI → evaluate → decide loop.
- Treat depth as 3: aim for 4,500–6,000 words if needed and up to 4 rounds of iteration in the draft log before the final keep.
- Open with a one‑sentence conclusion.
- Keep one idea per paragraph. Prefer code and data to prose. Short sentences mixed with longer ones.
- Include a clear Failure section that spells out what didn’t work and why. Use numbers and concrete settings.
- Include a fenced code block that readers can run locally.
- Reference the CSV by filename mini_experiment.csv and use it to back at least one claim with numbers.
- Reference other inputs by filename where relevant: project_readme.md, autoresearch_philosophy.md, notes.md.

Process
- Build research_facts.md first as a structured checklist.
- Draft, run a fast de‑AI pass, then self‑score on six dimensions: information density, code/data ratio, failure showcase, conciseness, actionability, human feel.
- Decide: keep if composite ≥ 80. Otherwise rewrite. Early terminate if two consecutive rounds are within 5 points; take the higher score.

Style rules
- Zero filler. Show, don’t tell.
- One thing per paragraph.
- Experiments first; claims need code or data support.
- Record failures explicitly.
- Use first person and state opinions when relevant. Admit uncertainty.
- Use specific numbers; avoid vague language.

Banned phrases (must not appear in the final article; case-insensitive)
- Furthermore
- As we all know
- It's worth noting
- delve into
- ever‑evolving landscape
- Not only
- but also

Must-include
- At least one fenced code block.
- At least one paragraph that references and interprets values from mini_experiment.csv.
- A Failure section with a heading that contains the word “Failure”, or the phrase “what didn’t work” included in that section.
- References by filename to project_readme.md and autoresearch_philosophy.md where appropriate.

Constraints
- Use only files under input/.
- No network requests.
- Keep a human voice; vary sentence length; keep the tone direct and practical.
- The final article should be reproducible by someone with the files in input/ and a Python setup as described in project_readme.md.

Success criteria for the article
- Strong code/data ratio with at least one runnable code snippet that reads and analyzes mini_experiment.csv.
- Data-backed claims about training behavior (e.g., validation loss trends, dropout effect).
- A transparent Failure section with reasons and follow-ups.
- High information density and concision, while keeping a human feel.