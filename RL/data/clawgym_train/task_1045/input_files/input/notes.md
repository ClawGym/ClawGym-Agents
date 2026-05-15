Working title
- “A tiny trainer, a tiny dataset, and why small changes beat grand theories.”

One-sentence conclusion (draft)
- A tiny transformer improves reliably with small, measured changes, and the same loop that trains it also keeps the writing honest.

Key facts to include
- Single-file script, train.py. Defaults: 6 layers, 6 heads, dim 384, context 256, BPE 8,192 merges or char-level fallback.
- Optimizer AdamW, cosine LR with 200-step warmup, bf16 if available.
- Default run that generated mini_experiment.csv used: lr=3e-4, batch_size=16, grad_accum=4, dropout=0.0, context=256.
- mini_experiment.csv contains steps 0..1100 in 100-step increments; at step 700 we temporarily set dropout=0.2 and val loss rose.

Experiments (short)
- Baseline A: lr=3e-4, grad_accum=4, dropout=0.0 → val_loss: 2.45 → 1.87 by step 1000. Throughput ~64 tokens/s.
- Dropout test: set dropout=0.2 at step 700 → val_loss ticked up from 1.95 to ~1.99. Reverted to 0.0 afterward.
- Cosine LR taper from 3e-4 down to ~2.4e-4 by step 1000.

Failures (what didn’t work, why)
- lr=1e-3 trial (not in the CSV excerpt): with bf16, we saw gradient overflow warnings and an early spike in val_loss to ~3.2 by ~step 300. Hypothesis: step size too large for this shallow network and small batch/accum combo.
- Tokenizer mismatch (a separate attempt): switching from BPE to char-level mid-way invalidated comparison; the vocabulary changed, making prior loss curves incomparable. Lesson: lock tokenizer per run.
- High dropout early (≥0.3) slowed learning on this small model; capacity is limited and regularization hit too hard.

What to show in code
- A minimal Python snippet that reads mini_experiment.csv, finds the best step, and prints a short summary (see project_readme.md snippet).
- Optional small moving average.

Points of view
- Prefer tiny, controlled changes. Stray opinions welcome as long as numbers back them.
- Throughput matters on laptops. Tokens/sec differences of 3–5 matter when iterations are short.

Limitations to acknowledge
- Tiny model and tiny dataset; improvements may not transfer to larger setups.
- Validation loss only; no downstream task measured here.

References by filename
- project_readme.md (features and defaults)
- mini_experiment.csv (evidence of trends and the dropout spike)
- autoresearch_philosophy.md (loop and six-dimension evaluation)