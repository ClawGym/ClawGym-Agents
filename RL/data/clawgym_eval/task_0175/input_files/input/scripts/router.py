#!/usr/bin/env python3
"""
Booking router (baseline)

- Expects lineup at 'input/config/lineup.yaml' with structure:
  episodes:
    - episode_id: "E###"
      date: "YYYY-MM-DD"
      venue: "Venue Name"
      acts: ["Name A", "Name B", ...]
- Does not currently factor availability.
- Does not enforce a maximum number of primary acts.
- Outputs to 'output/episode_schedule.json' with keys:
  episode_id, date, venue, primary (acts), backups (empty), dropped_unavailable (empty).
"""
from pathlib import Path
import json
import yaml

LINEUP_PATH = Path("input/config/lineup.yaml")
OUTPUT_PATH = Path("output/episode_schedule.json")

def load_lineup(path=LINEUP_PATH):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    episodes = data.get("episodes", [])
    # Baseline expects 'acts'
    for ep in episodes:
        acts = ep.get("acts")
        if acts is None:
            acts = []
        ep["acts"] = acts
    return episodes

def build_schedule(episodes):
    schedule = []
    for ep in episodes:
        schedule.append({
            "episode_id": ep.get("episode_id"),
            "date": str(ep.get("date")),
            "venue": ep.get("venue"),
            "primary": list(ep.get("acts", [])),
            "backups": [],
            "dropped_unavailable": []
        })
    return schedule

def main():
    episodes = load_lineup()
    schedule = build_schedule(episodes)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(schedule, f, indent=2)

if __name__ == "__main__":
    main()
