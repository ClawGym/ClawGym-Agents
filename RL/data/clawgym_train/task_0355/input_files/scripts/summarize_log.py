import argparse
import csv
import json
from datetime import datetime, time
from collections import defaultdict
import os

# Summarize a playback log given a config file.
# Outputs a JSON file with counts and averages that support compliance checks.

def parse_hhmm(s):
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def in_range(t, start, end):
    # Half-open interval: start <= t < end
    return (t >= start) and (t < end)


def main():
    ap = argparse.ArgumentParser(description="Summarize playback log for compliance metrics.")
    ap.add_argument("--log", required=True, help="Path to CSV playback log")
    ap.add_argument("--config", required=True, help="Path to player config JSON")
    ap.add_argument("--out", required=True, help="Path to write summary JSON")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    bh_start = parse_hhmm(cfg["business_hours"]["start"])  # e.g., 06:00
    bh_end = parse_hhmm(cfg["business_hours"]["end"])      # e.g., 22:00
    er_start = parse_hhmm(cfg["explicit_restricted_hours"]["start"])  # e.g., 06:00
    er_end = parse_hhmm(cfg["explicit_restricted_hours"]["end"])      # e.g., 17:00
    explicit_filter_enabled = bool(cfg.get("explicit_filter_enabled", False))
    max_volume = int(cfg.get("max_volume", 70))

    total_tracks = 0
    explicit_tracks = 0
    explicit_during_restricted = 0
    plays_outside_business_hours = 0
    loud_plays_over_max = 0

    volumes = []
    vol_by_hour = defaultdict(list)  # hour -> list of volumes

    with open(args.log, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_tracks += 1
            # Parse timestamp and volume/flags
            ts = row["timestamp"].strip()
            try:
                dt = datetime.fromisoformat(ts)
            except Exception:
                # Fallback: try replacing space with T if someone edited CSV
                dt = datetime.fromisoformat(ts.replace(" ", "T"))
            t = dt.time()
            vol = int(row["volume"].strip())
            exp_flag = str(row["explicit"]).strip().lower() in ("true", "1", "yes", "y")

            # Counters
            if exp_flag:
                explicit_tracks += 1
                if in_range(t, er_start, er_end):
                    explicit_during_restricted += 1

            if not in_range(t, bh_start, bh_end):
                plays_outside_business_hours += 1

            if vol > max_volume:
                loud_plays_over_max += 1

            volumes.append(vol)
            vol_by_hour[f"{dt.hour:02d}"].append(vol)

    avg_overall = round(sum(volumes) / len(volumes), 3) if volumes else 0.0
    avg_by_hour = {h: round(sum(vs) / len(vs), 3) for h, vs in sorted(vol_by_hour.items())}

    result = {
        "total_tracks": total_tracks,
        "explicit_tracks": explicit_tracks,
        "explicit_during_restricted_hours": explicit_during_restricted,
        "plays_outside_business_hours": plays_outside_business_hours,
        "loud_plays_over_max": loud_plays_over_max,
        "avg_volume_overall": avg_overall,
        "avg_volume_by_hour": avg_by_hour,
        "config": {
            "business_hours": cfg["business_hours"],
            "explicit_restricted_hours": cfg["explicit_restricted_hours"],
            "explicit_filter_enabled": explicit_filter_enabled,
            "max_volume": max_volume
        }
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as out_f:
        json.dump(result, out_f, indent=2)


if __name__ == "__main__":
    main()
