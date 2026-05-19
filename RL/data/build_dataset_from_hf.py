#!/usr/bin/env python3
"""Convert the public ClawGym-Task corpus on Hugging Face into the directory
layout consumed by the ClawGym-RL trainer (see ``data/DATASET_README.md``).

The Hugging Face dataset ``RUC-AIBOX/ClawGym-Task`` ships a single file
``syn_task.jsonl`` containing ~13.5K executable tasks. Each line is a JSON
object of the form::

    {
        "prompt": "user query...",
        "hook_code": "python3 reward/test.py /root/.openclaw/workspace",
        "input_files": [
            {"file_path": "reward/test.py", "content": "..."},
            {"file_path": "input/data.csv",  "content": "..."}
        ],
        "rule": null,
        "origin_template": "---\\nid: task_00_xyz\\n..."
    }

The script materialises one directory per task::

    <output_dir>/<task_id>/
        data_entry.json
        reward/
            check.py
            reward.sh        # <- always normalised to the canonical form
        input_files/
            input/data.csv

Usage:

    # Convert the entire HF corpus into ./clawgym_full/ (default repo + file)
    python tools/build_dataset_from_hf.py --output ./clawgym_full

    # Convert a previously-downloaded JSONL
    python tools/build_dataset_from_hf.py --input ./syn_task.jsonl \\
        --output ./clawgym_full
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterator

DEFAULT_REPO_ID = "RUC-AIBOX/ClawGym-Task"
DEFAULT_FILENAME = "syn_task.jsonl"
WORKSPACE = "/root/.openclaw/workspace"

# Standard reward.sh wrapper: invoke check.py, then average dict values OR
# pass through scalar to a final float in [0, 1].
REWARD_SH_TEMPLATE = """\
#!/usr/bin/env bash
set -euo pipefail

{hook} | python3 -c 'import json, sys; raw = sys.stdin.read().strip(); \
data = json.loads(raw); \
print(sum(float(v) for v in data.values()) / len(data) \
if isinstance(data, dict) and data \
else float(data) if isinstance(data, (int, float)) else 0.0)'
"""


def _download_from_hf(repo_id: str, filename: str, cache_dir: str | None) -> Path:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        sys.exit(
            "huggingface_hub is required to download from HF. "
            "Install it with: pip install huggingface_hub\n"
            f"(import error: {e})"
        )
    print(f"Downloading {filename} from {repo_id} ...", flush=True)
    local_path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        repo_type="dataset",
        cache_dir=cache_dir,
    )
    return Path(local_path)


def _iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  warn: skipping malformed line {line_no}: {e}", file=sys.stderr)


def _extract_task_id(origin_template: str) -> str:
    for line in origin_template.split("\n"):
        line = line.strip()
        if line.startswith("id:"):
            return line.split(":", 1)[1].strip()
    return ""


def _normalise_hook(hook_code: str) -> str:
    """Rewrite the hook so that it always invokes ``reward/check.py`` from the
    workspace root, regardless of how the original snippet referred to it.
    """
    if not hook_code:
        return f"python3 {WORKSPACE}/reward/check.py {WORKSPACE}"
    h = hook_code
    h = h.replace(f"{WORKSPACE}/reward/", "reward/")
    h = h.replace("reward/test.py", "reward/check.py")
    h = h.replace("reward/check.py", f"{WORKSPACE}/reward/check.py")
    return h


def convert(input_jsonl: Path, output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    n_written = 0
    n_skipped = 0

    for idx, d in enumerate(_iter_jsonl(input_jsonl)):
        task_id = _extract_task_id(d.get("origin_template", "")) or f"task_{idx:05d}"
        task_dir = output_dir / task_id
        if task_dir.exists():
            n_skipped += 1
            continue
        task_dir.mkdir(parents=True, exist_ok=True)

        # Split files into reward/ vs input_files/
        reward_files: list[dict] = []
        input_files: list[dict] = []
        for f_entry in d.get("input_files", []) or []:
            (reward_files if f_entry["file_path"].startswith("reward/") else input_files).append(f_entry)

        # data_entry.json
        entry: dict = {
            "task_id": task_id,
            "user_query": d.get("prompt", ""),
            "metadata": {"category": "", "grading_type": "automated"},
        }
        if d.get("rule"):
            entry["metadata"]["rule"] = d["rule"]
        if input_files:
            entry["input_mount_dir"] = WORKSPACE

        (task_dir / "data_entry.json").write_text(
            json.dumps(entry, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # reward/
        reward_dir = task_dir / "reward"
        reward_dir.mkdir(exist_ok=True)
        for rf in reward_files:
            sub_path = rf["file_path"].split("/", 1)[1]   # strip leading "reward/"
            if sub_path == "test.py":
                sub_path = "check.py"
            target = reward_dir / sub_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rf["content"], encoding="utf-8")

        reward_sh = REWARD_SH_TEMPLATE.format(hook=_normalise_hook(d.get("hook_code", "")))
        (reward_dir / "reward.sh").write_text(reward_sh, encoding="utf-8")
        os.chmod(reward_dir / "reward.sh", 0o755)

        # input_files/
        if input_files:
            input_dir = task_dir / "input_files"
            input_dir.mkdir(exist_ok=True)
            for if_entry in input_files:
                target = input_dir / Path(if_entry["file_path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(if_entry["content"], encoding="utf-8")

        n_written += 1
        if n_written % 500 == 0:
            print(f"  ... {n_written} tasks written")

    print(f"\nDone. Wrote {n_written} tasks to {output_dir} (skipped {n_skipped} already-existing).")
    return n_written


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, default=None,
                   help="Local syn_task.jsonl. If omitted, the file is fetched from Hugging Face.")
    p.add_argument("--output", type=Path, required=True,
                   help="Destination directory; one subdirectory per task is created here.")
    p.add_argument("--repo-id", default=DEFAULT_REPO_ID,
                   help=f"HF dataset repo id (default: {DEFAULT_REPO_ID}).")
    p.add_argument("--filename", default=DEFAULT_FILENAME,
                   help=f"File name within the HF repo (default: {DEFAULT_FILENAME}).")
    p.add_argument("--cache-dir", default=None,
                   help="HF hub cache directory (defaults to ~/.cache/huggingface).")
    args = p.parse_args()

    src = args.input or _download_from_hf(args.repo_id, args.filename, args.cache_dir)
    convert(src, args.output)


if __name__ == "__main__":
    main()
