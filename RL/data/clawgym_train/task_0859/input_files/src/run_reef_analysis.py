import argparse
import json
import os
import sys

from .reef_metrics import load_csv, compute_metrics


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute reef metrics and a simple stress index from a CSV.")
    ap.add_argument("--input", required=True, help="Path to input CSV with headers: date,temp_c,ph,chl_ugL")
    ap.add_argument("--out", required=True, help="Path to write JSON summary output")
    args = ap.parse_args()

    try:
        rows = load_csv(args.input)
        summary = compute_metrics(rows)
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, sort_keys=True)
        print(f"OK wrote {args.out}")
        return 0
    except Exception:
        # Intentionally unhelpful error that you will improve
        sys.stderr.write("Error: bad data\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
