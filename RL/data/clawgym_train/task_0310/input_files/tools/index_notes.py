#!/usr/bin/env python3
import sys
import argparse
import yaml
import csv
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Index outreach event notes into a CSV")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    notes_dir = Path(cfg.get("notes_dir", "workspace/input/notes"))
    out_csv = Path(cfg.get("output_csv", "workspace/output/events_index.csv"))
    max_len = int(cfg.get("summary_max_len", 160))

    if not notes_dir.exists():
        # Intentional: raise a clear error if directory is wrong
        raise FileNotFoundError(f"Notes directory not found: {notes_dir}")

    files = sorted(notes_dir.glob("*.yaml"))
    rows = []
    for p in files:
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        date = data.get("date")
        title = data.get("title")
        tags = data.get("tags")
        summary = data.get("summary", "")
        if not isinstance(tags, list):
            # Intentional strictness: will need a small code adjustment if tags are strings
            raise ValueError(f"tags must be a list in file {p.name}")
        tags_str = ";".join([str(t).strip() for t in tags])
        if len(summary) > max_len:
            summary = summary[:max_len].rstrip()
        rows.append((date, title, tags_str, summary))

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "title", "tags", "summary"])
        for r in rows:
            w.writerow(r)

    print(f"Processed {len(rows)} events.")

if __name__ == "__main__":
    main()
