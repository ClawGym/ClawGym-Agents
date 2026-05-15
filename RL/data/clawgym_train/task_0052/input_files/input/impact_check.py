import argparse
import csv
import json
import sys

def main():
    parser = argparse.ArgumentParser(description="Screen rally route against protected zones.")
    parser.add_argument("--route", required=True, help="Path to route CSV with segment_id,zone_id")
    parser.add_argument("--zones", required=True, help="Path to protected zones JSON")
    args = parser.parse_args()

    try:
        with open(args.zones, "r", encoding="utf-8") as f:
            zones = json.load(f)
    except Exception as e:
        print(f"FATAL: Could not load zones file: {e}", file=sys.stderr)
        sys.exit(3)

    restrictions = {z.get("zone_id", ""): z.get("restriction", "") for z in zones}

    segments = []
    try:
        with open(args.route, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                segments.append({
                    "segment_id": (row.get("segment_id") or "").strip(),
                    "zone_id": (row.get("zone_id") or "").strip()
                })
    except Exception as e:
        print(f"FATAL: Could not load route file: {e}", file=sys.stderr)
        sys.exit(3)

    warn = 0
    err = 0
    total = 0

    for i, seg in enumerate(segments):
        total += 1
        sid = seg["segment_id"] or f"row{i+1}"
        zid = seg["zone_id"]
        if not zid:
            print(f"ERROR: Segment {sid} missing zone_id.")
            err += 1
            continue
        r = restrictions.get(zid, "")
        if r == "no-entry":
            print(f"ERROR: Segment {sid} intersects restricted zone {zid} (no-entry).")
            err += 1
        elif r in ("buffer-50m", "seasonal-closure"):
            detail = "Maintain ≥50 m buffer" if r == "buffer-50m" else "Restricted access under seasonal closure"
            print(f"WARNING: Segment {sid} intersects zone {zid} ({r}; {detail}).")
            warn += 1
        else:
            print(f"OK: Segment {sid} in zone {zid} is permissible.")

    print(f"SUMMARY: segments={total}, errors={err}, warnings={warn}")
    if err > 0:
        sys.exit(2)
    elif warn > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
