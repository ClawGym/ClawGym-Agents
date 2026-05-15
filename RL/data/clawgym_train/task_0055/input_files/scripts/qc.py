#!/usr/bin/env python3
import argparse
import csv
import json
import os
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="Simple QC for daily station temperatures")
    parser.add_argument("--data", required=True, help="Path to input CSV: date,station,temp_c")
    parser.add_argument("--config", required=True, help="Path to thresholds JSON with min_temp_c, max_temp_c")
    parser.add_argument("--outdir", required=True, help="Directory to write outputs")
    args = parser.parse_args()

    ts = datetime.utcnow().isoformat() + "Z"
    print(f"INFO: Starting QC run at {ts}")

    # Load thresholds
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    min_t = cfg.get("min_temp_c", -50)
    max_t = cfg.get("max_temp_c", 45)
    print(f"INFO: Thresholds min={min_t}C max={max_t}C from {args.config}")

    # Prepare output directory
    os.makedirs(args.outdir, exist_ok=True)

    rows_total = 0
    stations = set()
    warnings = []
    errors = []

    sums = {}
    counts = {}

    with open(args.data, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows_total += 1
            date = (row.get("date") or "").strip()
            stn = (row.get("station") or "").strip()
            temp_str = (row.get("temp_c") or "").strip()
            if stn:
                stations.add(stn)

            if temp_str == "":
                msg = f"Missing temperature at {date} station={stn}"
                print(f"ERROR: {msg}")
                errors.append(msg)
                continue
            try:
                temp = float(temp_str)
                # Record numeric for station means
                sums[stn] = sums.get(stn, 0.0) + temp
                counts[stn] = counts.get(stn, 0) + 1
                if temp < min_t or temp > max_t:
                    msg = f"Out-of-range temperature {temp}C at {date} station={stn} (min={min_t}, max={max_t})"
                    print(f"WARNING: {msg}")
                    warnings.append(msg)
            except ValueError:
                msg = f"Non-numeric temperature '{temp_str}' at {date} station={stn}"
                print(f"ERROR: {msg}")
                errors.append(msg)

    print(f"INFO: Loaded {rows_total} rows from {args.data} across {len(stations)} stations")
    print(f"INFO: Found {len(warnings)} warnings and {len(errors)} errors")

    # Write metrics per station
    metrics_path = os.path.join(args.outdir, "metrics.csv")
    with open(metrics_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["station", "mean_temp_c", "count_numeric"])
        for stn in sorted(stations):
            cnt = counts.get(stn, 0)
            if cnt > 0:
                mean_val = sums[stn] / cnt
            else:
                mean_val = "NA"
            writer.writerow([stn, mean_val, cnt])
    print(f"INFO: Wrote metrics to {metrics_path}")

    # Write QC summary JSON
    summary = {
        "run_timestamp": ts,
        "data_path": args.data,
        "config_path": args.config,
        "rows_total": rows_total,
        "stations_count": len(stations),
        "stations": sorted(list(stations)),
        "warnings_count": len(warnings),
        "errors_count": len(errors),
        "warnings": warnings,
        "errors": errors
    }
    summary_path = os.path.join(args.outdir, "qc_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(f"INFO: Wrote QC summary to {summary_path}")
    print("INFO: QC completed successfully")

if __name__ == "__main__":
    main()
