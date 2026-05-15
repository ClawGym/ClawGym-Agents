import sys
import os
import json
from datetime import datetime
from src.aggregator import read_events_csv, filter_by_date_range, aggregate_incidents_by_governorate, write_aggregates_csv

def main(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    input_csv = cfg["input_csv"]
    start_date = datetime.strptime(cfg["start_date"], "%Y-%m-%d").date()
    end_date = datetime.strptime(cfg["end_date"], "%Y-%m-%d").date()
    output_csv = cfg["output_csv"]

    events = read_events_csv(input_csv)
    filtered = filter_by_date_range(events, start_date, end_date)
    agg = aggregate_incidents_by_governorate(filtered)

    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    write_aggregates_csv(agg, output_csv)

if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/config.json"
    main(config_path)
