import json
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    required = [
        "start_date",
        "weeks",
        "cadence_per_week",
        "channels",
        "publish_days",
        "keywords_fallback",
    ]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"Missing required config keys: {', '.join(missing)}")
    if not isinstance(cfg["publish_days"], list) or not all(isinstance(x, int) and 0 <= x <= 6 for x in cfg["publish_days"]):
        raise ValueError("publish_days must be a list of integers 0=Mon..6=Sun")
    return cfg

def load_inventory(path):
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            r["tags"] = [t.strip() for t in r.get("tags", "").split(";") if t.strip()]
            r["keywords"] = [k.strip() for k in r.get("keywords", "").split(";") if k.strip()]
            rows.append(r)
    rows.sort(key=lambda r: int(r["id"]))
    return rows

def generate_calendar(cfg, topics):
    start = datetime.strptime(cfg["start_date"], "%Y-%m-%d").date()
    weeks = int(cfg["weeks"])
    cadence = int(cfg["cadence_per_week"])
    channels = list(cfg["channels"])
    publish_days = list(cfg["publish_days"])
    fallback_keywords = list(cfg["keywords_fallback"])

    items = []
    day_list = []
    for w in range(weeks):
        monday = start + timedelta(days=(w * 7))
        for d in publish_days[:cadence]:
            day = monday + timedelta(days=d)
            day_list.append(day)

    idx_topic = 0
    idx_channel = 0
    for d in day_list:
        t = topics[idx_topic % len(topics)]
        chan = channels[idx_channel % len(channels)]
        idx_topic += 1
        idx_channel += 1
        primary_tag = t["tags"][0] if t["tags"] else ""
        kws = t["keywords"] if t["keywords"] else (fallback_keywords + ([primary_tag] if primary_tag else []))
        item = {
            "week": ((d - start).days // 7) + 1,
            "publish_date": d.isoformat(),
            "channel": chan,
            "topic_id": t["id"],
            "title": t["title"],
            "primary_tag": primary_tag,
            "audience": t.get("audience", ""),
            "keywords": kws,
        }
        items.append(item)
    return items

def write_outputs(items, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "content_calendar.json"
    csv_path = out / "content_calendar.csv"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    fieldnames = ["week", "publish_date", "channel", "topic_id", "title", "primary_tag", "audience", "keywords"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for it in items:
            row = dict(it)
            row["keywords"] = ";".join(it["keywords"])
            w.writerow(row)
    print(f"Wrote {csv_path} and {json_path}")

def main():
    config_path = Path("config/config.json")
    inventory_path = Path("input/inventory.csv")
    try:
        cfg = load_config(config_path)
        print("Loaded config keys:", ", ".join(sorted(cfg.keys())))
        topics = load_inventory(inventory_path)
        print(f"Loaded {len(topics)} topics from {inventory_path}")
        items = generate_calendar(cfg, topics)
        write_outputs(items, Path("output"))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
