import argparse
import csv
import json
import math
import os
from typing import Dict, List

# NOTE: This script intentionally contains bugs to be fixed:
# - Uses OR instead of AND in price filter
# - Includes categories not in weights by defaulting weight to 1.0
# - Casts weights to int (truncating floats)
# - Treats non-numeric ratings as 0.0 instead of skipping
# - Uses an incorrect weighted score formula and sorts ascending


def read_weights(path: str) -> Dict[str, float]:
    weights = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cat = (row.get("category") or "").strip()
            if not cat:
                continue
            try:
                # BUG: truncates float weights
                weights[cat] = int(row.get("weight", "0") or 0)
            except Exception:
                weights[cat] = 0
    return weights


def stream_products(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def compute_weighted_score(prod: dict, weights: Dict[str, float]) -> float:
    cat = prod.get("category", "")
    # BUG: invalid ratings coerced to 0.0 and kept
    try:
        rating = float(prod.get("rating", 0))
    except Exception:
        rating = 0.0
    reviews = prod.get("reviews_count", 0)
    try:
        reviews = int(reviews)
    except Exception:
        reviews = 0
    # BUG: defaults to 1.0 for unknown categories
    w = weights.get(cat, 1.0)
    # BUG: wrong formula (should be rating * w * ln(1 + reviews))
    score = rating + (w * math.log(1 + reviews)) if reviews >= 0 else rating
    return score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--products", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    weights = read_weights(args.weights)

    total_records_input = 0
    filtered: List[dict] = []

    for prod in stream_products(args.products):
        total_records_input += 1
        price = prod.get("price")
        try:
            price = float(price)
        except Exception:
            continue
        # BUG: uses OR instead of AND for price range
        if price >= 5 or price <= 100:
            prod["weighted_score"] = compute_weighted_score(prod, weights)
            filtered.append(prod)

    # BUG: ascending sort
    filtered_sorted = sorted(filtered, key=lambda r: (r.get("weighted_score", 0), r.get("reviews_count", 0)))

    top_n = 10
    top = filtered_sorted[:top_n]

    # Write CSV
    csv_path = os.path.join(args.outdir, "top10.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "category", "price", "rating", "reviews_count", "weighted_score"])
        for r in top:
            writer.writerow([
                r.get("id", ""),
                r.get("name", ""),
                r.get("category", ""),
                r.get("price", ""),
                r.get("rating", ""),
                r.get("reviews_count", ""),
                r.get("weighted_score", "")
            ])

    # Summary JSON (may not match requirements yet)
    cats = {}
    for r in filtered:
        c = r.get("category", "")
        cats[c] = cats.get(c, 0) + 1

    summary = {
        "total_records_input": total_records_input,
        "total_records_filtered": len(filtered),
        "counts_by_category": cats,
        "categories_included": sorted(cats.keys()),
        "top_n": top_n,
    }

    with open(os.path.join(args.outdir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
