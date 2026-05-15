#!/usr/bin/env python3
import os
import json
import csv
from statistics import mean

CONFIG_PATH = "config/settings.json"


def load_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_reviews(csv_path):
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "film_title": r["film_title"].strip(),
                "creator_type": r["creator_type"].strip(),
                "creator_handle": r["creator_handle"].strip(),
                "sentiment": float(r["sentiment"]),
                "credibility_score": float(r["credibility_score"]),
                "review_date": r["review_date"].strip(),
                "notes": r["notes"].strip()
            })
    return rows


def summarize_by_creator_type(reviews):
    by_type = {}
    for r in reviews:
        t = r["creator_type"]
        if t not in by_type:
            by_type[t] = {"count": 0, "sentiments": [], "credibilities": []}
        by_type[t]["count"] += 1
        by_type[t]["sentiments"].append(r["sentiment"])
        by_type[t]["credibilities"].append(r["credibility_score"])
    summary = {}
    for t, agg in by_type.items():
        summary[t] = {
            "count": agg["count"],
            "avg_sentiment": round(mean(agg["sentiments"]), 3) if agg["sentiments"] else None,
            "avg_credibility": round(mean(agg["credibilities"]), 3) if agg["credibilities"] else None
        }
    return summary


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    config = load_config()
    reviews = read_reviews(config["input_csv"])
    summary = summarize_by_creator_type(reviews)
    out_dir = config.get("output_dir", "output")
    os.makedirs(out_dir, exist_ok=True)
    write_json(os.path.join(out_dir, "summary.json"), {"by_creator_type": summary})
    print("Wrote summary.json")


if __name__ == "__main__":
    main()
