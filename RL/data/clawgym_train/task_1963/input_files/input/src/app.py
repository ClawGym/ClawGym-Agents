"""
Simple CLI app demonstrating reading project data and utilities.
"""

from pathlib import Path
from utils.helpers import slugify, load_json, read_yaml, iter_jsonl


def project_root() -> Path:
    # In runtime this will be mounted under input/
    return Path(__file__).resolve().parents[2]


def show_overview() -> None:
    root = project_root()
    data_dir = root / "data"
    docs_dir = root / "docs"

    sample_json = data_dir / "sample.json"
    cfg_yaml = data_dir / "config.yaml"
    events_jsonl = data_dir / "events.jsonl"
    spec_md = docs_dir / "spec.md"

    print("# Project Overview")
    print(f"- Root: {root}")
    print(f"- Docs: {spec_md}")
    print(f"- Data files:")
    print(f"  - sample.json: {sample_json.exists()}")
    print(f"  - config.yaml: {cfg_yaml.exists()}")
    print(f"  - events.jsonl: {events_jsonl.exists()}")

    if sample_json.exists():
        data = load_json(sample_json)
        print(f"- Sample title: {data.get('title')}")
        print(f"- Slugified title: {slugify(data.get('title', 'untitled'))}")

    if cfg_yaml.exists():
        cfg = read_yaml(cfg_yaml)
        env = cfg.get("env", {})
        print(f"- Environment: {env.get('name', 'unknown')} ({env.get('mode', 'n/a')})")

    if events_jsonl.exists():
        count = sum(1 for _ in iter_jsonl(events_jsonl))
        print(f"- Event records: {count}")


if __name__ == "__main__":
    show_overview()