import os
import json
from pathlib import Path

INPUT_TASKS = Path("input/tasks.jsonl")
INPUT_WORKFLOW = Path("input/workflow.json")
OUTPUT_DIR = Path("output")
OUTPUT_ASSIGNED = OUTPUT_DIR / "assigned_tasks.jsonl"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path: Path):
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def write_jsonl(path: Path, records):
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def assign_tasks(tasks, rules, fallback):
    assigned = []
    for t in tasks:
        team = fallback
        tags = t.get("tags", [])
        for tag in tags:
            if tag in rules:
                team = rules[tag]
                break
        out = dict(t)
        out["assigned_team"] = team
        assigned.append(out)
    return assigned


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not INPUT_TASKS.exists():
        raise FileNotFoundError(f"Missing tasks file: {INPUT_TASKS}")
    if not INPUT_WORKFLOW.exists():
        raise FileNotFoundError(f"Missing workflow config: {INPUT_WORKFLOW}")

    workflow = load_json(INPUT_WORKFLOW)
    routing = workflow.get("routing", {})
    rules = routing.get("rules", {})
    fallback = routing.get("fallback_team", "unassigned")

    tasks = read_jsonl(INPUT_TASKS)
    assigned = assign_tasks(tasks, rules, fallback)
    write_jsonl(OUTPUT_ASSIGNED, assigned)

if __name__ == "__main__":
    main()
