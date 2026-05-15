#!/usr/bin/env python3
import sys
import csv
import collections

ALLOWED_TRIGGERS = {"isolation","claustrophobia","supernatural","body_horror","stalking","home_invasion"}


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("Usage: python tools/trigger_counter.py <input_annotations.csv> <output_summary.csv>\n")
        sys.exit(2)
    in_path = sys.argv[1]
    out_path = sys.argv[2]

    try:
        with open(in_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            required = {"film","scene_id","trigger","intensity"}
            if not required.issubset(reader.fieldnames or []):
                sys.stderr.write("ERROR: missing required columns. Found: %s. Required: %s\n" % (reader.fieldnames, sorted(required)))
                sys.exit(2)
            counts = collections.Counter()
            intensity_sums = collections.Counter()
            rows_seen = 0
            for row in reader:
                rows_seen += 1
                trig = (row.get("trigger") or "").strip()
                if trig not in ALLOWED_TRIGGERS:
                    sys.stderr.write(f"WARNING: unknown trigger '{trig}' on row {rows_seen}; skipping\n")
                    continue
                film = (row.get("film") or "").strip()
                key = (film, trig)
                try:
                    inten = int(str(row.get("intensity")).strip())
                except Exception:
                    sys.stderr.write(f"WARNING: bad intensity '{row.get('intensity')}' on row {rows_seen}; skipping\n")
                    continue
                counts[key] += 1
                intensity_sums[key] += inten
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: input file not found: {in_path}\n")
        sys.exit(2)

    with open(out_path, 'w', newline='', encoding='utf-8') as out:
        writer = csv.writer(out)
        writer.writerow(["film","trigger","count","avg_intensity"])
        for (film, trig), cnt in sorted(counts.items()):
            avg = intensity_sums[(film, trig)] / cnt if cnt else 0
            writer.writerow([film, trig, cnt, f"{avg:.2f}"])

    sys.stdout.write(f"Wrote {len(counts)} rows to {out_path}\n")


if __name__ == "__main__":
    main()
