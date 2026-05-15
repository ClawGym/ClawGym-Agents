#!/usr/bin/env python3
import os
import json
import csv
import argparse


def run(config_path: str) -> None:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    input_csv = cfg["input_csv"]
    site = cfg["site_id"]
    min_density = float(cfg["min_density"])
    max_depth = float(cfg["max_depth_cm"])
    output_dir = cfg.get("output_dir", "output")
    os.makedirs(output_dir, exist_ok=True)

    rows = []
    with open(input_csv, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    total_rows = len(rows)
    site_rows = [r for r in rows if r.get("site_id") == site]

    included_rows = []
    for r in site_rows:
        try:
            d = float(r.get("density_gcm3", "nan"))
            depth = float(r.get("depth_cm", "nan"))
        except ValueError:
            continue
        if d >= min_density and depth <= max_depth:
            included_rows.append(r)

    # Write filtered CSV
    filtered_csv_path = os.path.join(output_dir, f"filtered_{site}.csv")
    fieldnames = rows[0].keys() if rows else ["site_id","unit_id","layer","depth_cm","density_gcm3","sample_id"]
    with open(filtered_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in included_rows:
            writer.writerow(r)

    densities = [float(r["density_gcm3"]) for r in included_rows] if included_rows else []
    depths = [float(r["depth_cm"]) for r in included_rows] if included_rows else []

    mean_density = round(sum(densities) / len(densities), 3) if densities else None
    min_depth = min(depths) if depths else None
    max_depth_included = max(depths) if depths else None

    summary_json_path = os.path.join(output_dir, f"summary_{site}.json")
    summary = {
        "site_id": site,
        "input_csv": input_csv,
        "filters": {
            "min_density": min_density,
            "max_depth_cm": max_depth
        },
        "counts": {
            "total_rows": total_rows,
            "site_rows": len(site_rows),
            "included_rows": len(included_rows)
        },
        "stats": {
            "mean_density_included": mean_density,
            "min_depth_included": min_depth,
            "max_depth_included": max_depth_included
        },
        "outputs": {
            "filtered_csv": filtered_csv_path,
            "summary_json": summary_json_path
        }
    }

    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    print(f"Wrote {filtered_csv_path}")
    print(f"Wrote {summary_json_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filter stratigraphy samples by site and thresholds.")
    parser.add_argument("--config", default="config/pipeline.json", help="Path to JSON config file")
    args = parser.parse_args()
    run(args.config)
