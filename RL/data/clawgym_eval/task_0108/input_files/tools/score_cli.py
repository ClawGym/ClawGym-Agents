import sys
import csv
from collections import defaultdict

def main():
    if len(sys.argv) != 2:
        sys.stderr.write("USAGE: python tools/score_cli.py <path_to_voters_csv>\n")
        sys.exit(2)
    path = sys.argv[1]
    try:
        f = open(path, newline='', encoding='utf-8')
    except Exception as e:
        sys.stderr.write(f"ERROR could_not_open_file path={path} detail={e}\n")
        sys.exit(1)

    reader = csv.DictReader(f)
    required = {"id","ward","postcode","doorstep_score"}
    missing_headers = required - set(h.strip() for h in reader.fieldnames or [])
    if missing_headers:
        sys.stderr.write("ERROR missing_headers " + ",".join(sorted(missing_headers)) + "\n")
        sys.exit(1)

    stats = defaultdict(lambda: {"count": 0, "sum": 0.0})
    missing_pc_by_ward = defaultdict(int)

    for row in reader:
        rid = (row.get("id") or "").strip()
        ward = (row.get("ward") or "").strip()
        postcode = (row.get("postcode") or "").strip()
        ds = (row.get("doorstep_score") or "").strip()

        if not ward:
            sys.stderr.write(f"WARN missing ward row_id={rid}\n")
            continue

        try:
            score = float(ds)
        except Exception:
            sys.stderr.write(f"ERROR invalid doorstep_score row_id={rid} value={ds!r}\n")
            continue

        if not postcode:
            sys.stderr.write(f"WARN missing postcode row_id={rid} ward={ward}\n")
            missing_pc_by_ward[ward] += 1

        stats[ward]["count"] += 1
        stats[ward]["sum"] += score

    # Output summary as TSV to stdout
    out = sys.stdout
    out.write("ward\tcount_valid\tavg_score\tmissing_postcode_count\n")
    for ward in sorted(stats.keys()):
        c = stats[ward]["count"]
        s = stats[ward]["sum"]
        avg = s / c if c else 0.0
        mpc = missing_pc_by_ward.get(ward, 0)
        out.write(f"{ward}\t{c}\t{avg:.3f}\t{mpc}\n")

if __name__ == "__main__":
    main()
