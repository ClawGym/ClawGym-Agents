from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # Fallback; reader will raise if used without pyyaml


def slugify(text: str) -> str:
    """
    Create a simple URL-friendly slug from text.
    Not fully locale-aware; good enough for demos.
    """
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-"
    base = text.strip().lower().replace("_", "-").replace(" ", "-")
    # Collapse repeated dashes
    out = []
    last_dash = False
    for ch in base:
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        elif ch in "-./":
            if not last_dash:
                out.append("-")
                last_dash = True
        else:
            # drop punctuation
            if not last_dash:
                out.append("-")
                last_dash = True
    slug = "".join(out).strip("-")
    # remove any accidental unsupported chars
    return "".join(c for c in slug if c in allowed)


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed; cannot parse YAML.")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)