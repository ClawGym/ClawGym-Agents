# TinyLLMTrainer

A single-file, local-friendly training loop for a tiny decoder-only Transformer. Designed to run on a laptop or a single small GPU. The goal is clarity and fast iteration, not benchmark records.

## Files

- train.py — end-to-end training script (model, optimizer, schedule, training/eval loop).
- prepare.py — optional data prep; turns a text file into token IDs with a tiny BPE (or uses character-level if you prefer zero dependencies).
- README (this file).

This repo keeps things minimal on purpose so you can read it in one sitting and start modifying right away.

## Model

- Decoder-only Transformer (GPT-like), small width
- Default config:
  - layers: 6
  - heads: 6
  - embed dim: 384
  - vocab size: 8,192 (tiny BPE) or 256 (char-level)
  - max context length: 256 tokens
  - dropout: 0.0 by default
- Weight tying enabled; GELU activations; layernorm pre-attention.

## Training loop (high level)

- Optimizer: AdamW (β1=0.9, β2=0.95, weight_decay=0.1)
- LR schedule: cosine with warmup steps (default warmup 200)
- Mixed precision: bf16 if available; fallback to fp32
- Gradient accumulation to simulate larger batch sizes
- Validation every `eval_interval` steps on a held-out split
- Simple CSV logging (see below)

## Data

- You provide a small text corpus. TinyStories, Shakespeare, or your own project text works fine.
- Use prepare.py to build token files:
  ```bash
  python prepare.py --input data/tinystories.txt --out_dir data/ --bpe_merges 8192
  ```
- Character-level fallback example:
  ```bash
  python prepare.py --input data/shakespeare.txt --out_dir data/ --char_level
  ```

## Usage

Train with defaults:

```bash
python train.py \
  --data_dir data/ \
  --context 256 \
  --vocab bpe8192.json \
  --batch_size 16 \
  --grad_accum 4 \
  --lr 3e-4 \
  --dropout 0.0 \
  --eval_interval 100 \
  --max_steps 1100 \
  --log_csv outputs/run_log.csv
```

- The script prints step-wise train/val loss and tokens/sec.
- It writes a CSV with columns:
  `step,train_loss,val_loss,lr,tokens_per_sec,batch_size,grad_accum,dropout,notes`.

For this article, a tiny excerpt of a run is provided in `mini_experiment.csv` (in the input/ folder), mirroring the format above. It shows the default run with a brief dropout experiment at step 700.

## Why this project

- Single file you can read top-to-bottom.
- Modest defaults that run on a laptop GPU (or CPU if patient).
- CSV logging you can inspect with a few lines of Python.

## Typical workflow

1. Start with safe defaults (`lr=3e-4`, `dropout=0.0`, `grad_accum=4`, `context=256`).
2. Verify the loop runs and logs to CSV.
3. Add small, isolated changes and measure impact within 1,000–2,000 steps.
4. Keep a run log as CSV and compare runs by validation loss and throughput.

## Snippet: reading the CSV and picking the best step

The following snippet scans a run log and reports the step with the lowest validation loss. You can use it directly with `mini_experiment.csv`.

```python
import csv
from math import inf

best = {"step": None, "val_loss": inf}
rows = []
with open("mini_experiment.csv", "r", newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        row["step"] = int(row["step"])
        row["val_loss"] = float(row["val_loss"])
        rows.append(row)
        if row["val_loss"] < best["val_loss"]:
            best = {"step": row["step"], "val_loss": row["val_loss"]}

print(f"Best val_loss {best['val_loss']:.3f} at step {best['step']}")
# Example follow-up: simple moving average of val_loss over a 3-point window
def moving_avg(vals, k=3):
    out = []
    for i in range(len(vals)):
        window = vals[max(0, i-k+1):i+1]
        out.append(sum(window)/len(window))
    return out

vals = [r["val_loss"] for r in rows]
smoothed = moving_avg(vals, k=3)
print("Smoothed tail:", [round(x, 3) for x in smoothed[-5:]])
```

## Known pitfalls (see notes.md for details)

- Too aggressive LR (≥1e-3) can destabilize this tiny model, especially with bf16.
- High dropout on a small model hurts early convergence.
- Tokenizer mismatch (switching from BPE to char mid-run) can make comparisons invalid.

## License

MIT-like, do what you want. Credit welcome.