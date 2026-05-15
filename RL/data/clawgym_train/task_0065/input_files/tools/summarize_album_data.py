import json
import csv
import os
from statistics import mean

INPUT_JSON = "input/library.json"
INPUT_COSTS = "input/pressing_costs.csv"
OUT_DIR = os.path.join("outputs", "data")
OUT_PATH = os.path.join(OUT_DIR, "metrics.json")

PHYSICAL_FORMATS = {"Vinyl", "CD"}


def load_library(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_costs(path):
    costs = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fmt = row["format"].strip()
            try:
                costs[fmt] = float(row["unit_cost_usd"].strip())
            except Exception:
                raise ValueError(f"Invalid unit_cost_usd for format {fmt}")
    return costs


def compute_metrics(library, costs):
    total = len(library)
    physical_count = sum(1 for item in library if item.get("format") in PHYSICAL_FORMATS)
    digital_count = sum(1 for item in library if item.get("format") == "Digital")
    years = [item.get("year") for item in library if isinstance(item.get("year"), int)]
    avg_year = round(mean(years), 1) if years else None

    bitrates = [item.get("bitrate_kbps") for item in library if isinstance(item.get("bitrate_kbps"), (int, float))]
    avg_bitrate = round(mean(bitrates), 1) if bitrates else None

    replacement_cost = 0.0
    for item in library:
        fmt = item.get("format")
        if fmt not in costs:
            raise KeyError(f"Missing cost for format: {fmt}")
        replacement_cost += costs[fmt]

    physical_share_percent = round((physical_count / total) * 100.0, 2) if total else 0.0

    return {
        "total_count": total,
        "physical_count": physical_count,
        "digital_count": digital_count,
        "physical_share_percent": physical_share_percent,
        "avg_year": avg_year,
        "avg_bitrate_digital_kbps": avg_bitrate,
        "est_replacement_cost_usd": round(replacement_cost, 2)
    }


def main():
    library = load_library(INPUT_JSON)
    costs = load_costs(INPUT_COSTS)
    metrics = compute_metrics(library, costs)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
