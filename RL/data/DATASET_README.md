# Datasets

Two ready-to-use splits in this repository:

| Split      | Path                  | Tasks |
| ---------- | --------------------- | ----- |
| Training   | `data/clawgym_train/` | 2000  |
| Evaluation | `data/clawgym_eval/`  | 200   |

## Rebuild from Hugging Face

The full ~15.6K-task corpus is hosted at
[RUC-AIBOX/ClawGym-Task](https://huggingface.co/datasets/RUC-AIBOX/ClawGym-Task).
[data/build_dataset_from_hf.py](build_dataset_from_hf.py) downloads it and
writes the per-task directory layout in one step:

```bash
python data/build_dataset_from_hf.py --output ./clawgym_full
```

Pass `--input syn_task.jsonl` to convert a local copy instead.

The 2000 selected training tasks in our folder are curated based on these principles:

- **Tool-call diversity** — subsampled to balance tool invocations.
- **No web tools** — `web_search` / `web_fetch` related tasks are excluded;
  network tools dominate latency and cause cascading timeouts when running in large-scale parallel sandboxes.

## Format

```text
dataset/
  task_0000/
    data_entry.json
    input_files/                # optional, mirrored into the workspace
      input/data.csv
    reward/
      reward.sh                 # required entry point; prints final score
      check.py                  # arbitrary helpers
```

`data_entry.json`:

```json
{
  "task_id": "task_0000",
  "user_query": "Read input/data.csv and write the answer to output/answer.txt.",
  "input_mount_dir": "/root/.openclaw/workspace",
  "metadata": {"category": "", "grading_type": "automated"}
}
```

- `input_files/` is copied verbatim to `input_mount_dir` (typically
  `/root/.openclaw/workspace`); omit `input_mount_dir` when there are no input
  files.
- `reward/` is copied to `/root/.openclaw/workspace/reward/`. `reward.sh` runs
  after the agent terminates and must print one float in `[0, 1]` as the last
  line of stdout. The recommended pattern delegates to a `check.py` that emits
  a JSON dict of named sub-scores, then averages them:

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  python3 /root/.openclaw/workspace/reward/check.py /root/.openclaw/workspace \
    | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); \
  print(sum(map(float,d.values()))/len(d) if isinstance(d,dict) and d \
  else float(d) if isinstance(d,(int,float)) else 0.0)'
  ```

  ```python
  # check.py
  import json, sys
  from pathlib import Path

  def grade(workspace: str) -> dict:
      ws = Path(workspace)
      ans = ws / "output" / "answer.txt"
      return {
          "file_exists":     1.0 if ans.is_file() else 0.0,
          "content_correct": 1.0 if ans.is_file() and ans.read_text().strip() == "150" else 0.0,
      }

  if __name__ == "__main__":
      print(json.dumps(grade(sys.argv[1] if len(sys.argv) > 1 else ".")))
  ```

For chat-style tasks that grade the agent's final assistant message rather
than workspace state, the rollout exports `OPENCLAW_REWARD_PAYLOAD` pointing
at a JSON file containing `{task_id, user_query, metadata, final_message,
transcript}`; `reward.sh` may consume that instead.
