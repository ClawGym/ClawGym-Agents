#!/usr/bin/env python3
import sys
import csv
import argparse
import math


def main():
    ap = argparse.ArgumentParser(description="Compute buzz scores for Dutch entertainment events.")
    ap.add_argument("--in", dest="infile", required=True, help="Input CSV with columns: name,category,city,month,avg_rating,review_count (rating cols may be blank).")
    ap.add_argument("--out", dest="outfile", required=True, help="Output CSV path.")
    args = ap.parse_args()

    required_cols = ["name", "category", "city", "month", "avg_rating", "review_count"]
    rows = []

    try:
        with open(args.infile, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            missing = [c for c in required_cols if c not in reader.fieldnames]
            if missing:
                sys.stderr.write("ERROR missing_columns: " + ",".join(missing) + "\n")
                return 2
            for r in reader:
                rows.append(r)
    except FileNotFoundError:
        sys.stderr.write("ERROR file_not_found: " + args.infile + "\n")
        return 2

    warnings = 0
    out_rows = []
    for r in rows:
        name = (r.get("name") or "").strip()
        cat = (r.get("category") or "").strip()
        city = (r.get("city") or "").strip()
        month = (r.get("month") or "").strip()
        avg_rating = (r.get("avg_rating") or "").strip()
        review_count = (r.get("review_count") or "").strip()
        avg_val = None
        rev_val = None
        buzz = ""
        if avg_rating and review_count:
            try:
                avg_val = float(avg_rating)
                # Accept integer-like floats too
                rev_val = int(float(review_count))
                buzz_val = avg_val * (1.0 + math.log1p(max(rev_val, 0)))
                buzz = f"{buzz_val:.6f}"
            except Exception:
                warnings += 1
                sys.stderr.write(f"WARN invalid_rating: {name}\n")
                avg_val = None
                rev_val = None
                buzz = ""
        else:
            warnings += 1
            sys.stderr.write(f"WARN missing_rating: {name}\n")
        out_rows.append({
            "name": name,
            "category": cat,
            "city": city,
            "month": month,
            "avg_rating": f"{avg_val:.3f}" if isinstance(avg_val, float) else "",
            "review_count": str(rev_val) if isinstance(rev_val, int) else "",
            "buzz_score": buzz
        })

    try:
        with open(args.outfile, "w", newline='', encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "category", "city", "month", "avg_rating", "review_count", "buzz_score"])
            writer.writeheader()
            writer.writerows(out_rows)
    except Exception as e:
        sys.stderr.write("ERROR write_failed: " + str(e) + "\n")
        return 2

    sys.stdout.write(f"Processed {len(rows)} rows\n")
    sys.stdout.write(f"Warnings: {warnings}\n")
    sys.stdout.write(f"Wrote: {args.outfile}\n")
    return 0


if __name__ == "__main__":
    rc = main()
    if isinstance(rc, int) and rc != 0:
        sys.exit(rc)
