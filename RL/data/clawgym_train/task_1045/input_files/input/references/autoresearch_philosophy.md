# Mapping the modify → humanize → self‑evaluate → decide loop to writing

Source intent: adapt the core loop from iterative experimentation into a writing workflow where each pass is a measured experiment rather than freeform prose.

## The loop

- Modify (Phase 1): write or rewrite a full draft, focusing on experiments and specific claims.
- Humanize (Phase 1.5): fast de‑AI pass that removes filler and stereotyped phrasing, breaks formulaic structures, and injects voice (opinions, mixed sentence lengths, uncertainty where real).
- Self‑evaluate (Phase 2): score the draft with six dimensions and written notes.
- Decide (Phase 3): keep if composite ≥ 80; otherwise, rewrite only the weakest dimensions. Early terminate if two consecutive rounds are within 5 points; keep the higher score.

## Six dimensions (0–100; weights in parentheses)

1) Information density (20%) — nearly every sentence carries new info; avoid setup padding.
2) Code/data ratio (20%) — claims backed by runnable code or data from the workspace.
3) Failure showcase (15%) — includes what didn’t work and why, with concrete settings.
4) Conciseness (15%) — one idea per paragraph; deleting any paragraph should remove value.
5) Actionability (15%) — reader can reproduce numbers or steps immediately.
6) Human feel (15%) — real voice, varied rhythm, opinions, and zero stereotyped AI phrasing.

Composite:
score = info_density*0.20 + code_data*0.20 + failure*0.15 + conciseness*0.15 + actionability*0.15 + human_feel*0.15

## Built‑in de‑AI rules (fast pass)

- Kill filler bromides and emphasis crutches.
- Replace vague intensifiers with numbers.
- Break rule‑of‑three lists; use two or four.
- Avoid generic “future is bright” endings; end with a limitation or next step.
- Inject voice deliberately: a short blunt sentence, then a longer one that develops.

Banned phrases (must be kept out of the final article)
- Furthermore
- As we all know
- It's worth noting
- delve into
- ever‑evolving landscape
- Not only
- but also

## How to apply this to TinyLLMTrainer

- Facts from project_readme.md establish the training loop and defaults.
- Data from mini_experiment.csv must back claims (e.g., best validation loss, dropout effect).
- Rough ideas in notes.md suggest failures to include and analyze.
- The article should begin with a one‑sentence conclusion, then show code/data, then call out limitations.