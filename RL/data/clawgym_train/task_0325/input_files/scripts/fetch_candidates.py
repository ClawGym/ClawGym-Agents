#!/usr/bin/env python3
"""
Starter script for building treaty search queries and (to be extended) performing
web searches. Update this script to meet the task requirements:
- read input/treaties.csv and config/sources.yaml
- enforce per-treaty domain whitelist
- perform live search engine queries according to config search.engine_preference
- write outputs under output/ and logs/ as specified in the task
"""
import csv
import json
import sys
import pathlib
from datetime import datetime

try:
    import yaml
except Exception:
    print("PyYAML not installed; install it before running.", file=sys.stderr)

INPUT_CSV = pathlib.Path("input/treaties.csv")
CONFIG_YAML = pathlib.Path("config/sources.yaml")
# NOTE: The spec expects 'output' and 'logs' directories. These defaults are intentionally mismatched.
OUTPUT_DIR = pathlib.Path("outputs")  # TODO: change to 'output'
LOG_PATH = pathlib.Path("log/search_log.jsonl")  # TODO: change to 'logs/search_log.jsonl'


def load_config():
    with CONFIG_YAML.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def planned_query(treaty_name, allowed_domains):
    site_filter = " OR site:".join(allowed_domains) if allowed_domains else ""
    if site_filter:
        site_filter = " site:" + site_filter
    return f"{treaty_name} official text{site_filter}"


def main():
    cfg = load_config()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # This starter only writes planned queries; extend to perform real searches and write full outputs per spec.
    plan_csv = OUTPUT_DIR / "plans.csv"
    with INPUT_CSV.open("r", encoding="utf-8") as f, plan_csv.open("w", encoding="utf-8", newline="") as out:
        reader = csv.DictReader(f)
        fieldnames = [
            "treaty_id",
            "treaty_name",
            "org_hint",
            "query",
            "engine_pref",
            "allowed_domains",
        ]
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        engine_pref = ",".join(cfg.get("search", {}).get("engine_preference", []))
        for row in reader:
            allowed = cfg.get("domains", {}).get(row["org_hint"], {}).get("allowed", [])
            q = planned_query(row["treaty_name"], allowed)
            writer.writerow({
                "treaty_id": row["treaty_id"],
                "treaty_name": row["treaty_name"],
                "org_hint": row["org_hint"],
                "query": q,
                "engine_pref": engine_pref,
                "allowed_domains": ";".join(allowed),
            })


if __name__ == "__main__":
    main()
