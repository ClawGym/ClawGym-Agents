import sys, csv

def is_missing(s):
    return s is None or str(s).strip() == ""

def to_float(s):
    try:
        return float(s)
    except Exception:
        return None

def main():
    if len(sys.argv) != 2:
        sys.stderr.write("USAGE: python3 check_data.py <readings.csv>\n")
        sys.exit(2)
    path = sys.argv[1]
    errors = 0
    warnings = 0
    with open(path, newline='') as f:
        rdr = csv.DictReader(f)
        for i, row in enumerate(rdr, start=2):
            unit = row.get('unit_id', '').strip()
            ts = row.get('timestamp', '').strip()
            e_s = row.get('energy_kwh')
            r_s = row.get('runtime_hours')
            # Validate runtime
            if is_missing(r_s):
                sys.stderr.write(f"ERROR unit={unit} timestamp={ts} reason=runtime_missing\n")
                errors += 1
                continue
            r_v = to_float(r_s)
            if r_v is None:
                sys.stderr.write(f"ERROR unit={unit} timestamp={ts} reason=runtime_non_numeric\n")
                errors += 1
                continue
            if r_v <= 0:
                sys.stderr.write(f"ERROR unit={unit} timestamp={ts} reason=runtime_nonpositive\n")
                errors += 1
                continue
            # Validate energy
            if is_missing(e_s):
                sys.stderr.write(f"ERROR unit={unit} timestamp={ts} reason=energy_missing\n")
                errors += 1
                continue
            e_v = to_float(e_s)
            if e_v is None:
                sys.stderr.write(f"ERROR unit={unit} timestamp={ts} reason=energy_non_numeric\n")
                errors += 1
                continue
            if e_v < 0:
                sys.stdout.write(f"WARNING unit={unit} timestamp={ts} reason=negative_energy\n")
                warnings += 1
                # no continue: warnings do not invalidate row
        sys.stdout.write(f"SUMMARY errors={errors} warnings={warnings}\n")
    sys.exit(1 if errors > 0 else 0)

if __name__ == '__main__':
    main()
