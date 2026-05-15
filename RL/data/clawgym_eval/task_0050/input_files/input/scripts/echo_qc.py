import sys, csv

# Simple QC for pediatric vitals
# Usage: python echo_qc.py input/data/patient_vitals.csv
# Emits INFO and WARNING to stdout; ERROR to stderr. Exits with code 1 if any ERRORs occurred.

def parse_int(val):
    val = (val or '').strip()
    if val == '':
        return None
    try:
        return int(val)
    except ValueError:
        return None

def main():
    if len(sys.argv) != 2:
        print('ERROR: Expected one CSV path argument', file=sys.stderr)
        sys.exit(2)
    csv_path = sys.argv[1]
    rows = []
    try:
        with open(csv_path, newline='') as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
    except FileNotFoundError:
        print(f'ERROR: File not found {csv_path}', file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f'ERROR: Failed to read CSV: {e}', file=sys.stderr)
        sys.exit(2)

    print(f'INFO: Loaded {len(rows)} records from {csv_path}')

    errors = 0
    warnings = 0
    infos = 1  # count the initial INFO above

    for r in rows:
        pid = (r.get('patient_id') or '').strip() or 'UNKNOWN'
        age_m = parse_int(r.get('age_months'))
        hr = parse_int(r.get('heart_rate_bpm'))
        spo2 = parse_int(r.get('spo2'))

        # Missing heart rate is an ERROR
        if hr is None:
            print(f"ERROR [patient_id={pid}]: Missing heart_rate_bpm", file=sys.stderr)
            errors += 1
        else:
            # Implausible HR thresholds
            if hr < 50 or hr > 220:
                print(f"ERROR [patient_id={pid}]: Implausible heart rate {hr} bpm", file=sys.stderr)
                errors += 1
            # Infant-specific HR warnings (age < 12 months)
            elif age_m is not None and age_m < 12:
                if hr < 100:
                    print(f"WARNING [patient_id={pid}]: Infant heart rate borderline low ({hr} bpm; expected 100-160)")
                    warnings += 1
                elif hr > 160:
                    print(f"WARNING [patient_id={pid}]: Infant heart rate high ({hr} bpm; expected 100-160)")
                    warnings += 1

        # SpO2 check: low saturation is an ERROR
        if spo2 is not None and spo2 < 92:
            print(f"ERROR [patient_id={pid}]: Low SpO2 {spo2}%", file=sys.stderr)
            errors += 1

    print(f"INFO: Completed QC — {errors} error(s), {warnings} warning(s)")
    infos += 1

    sys.exit(1 if errors > 0 else 0)

if __name__ == '__main__':
    main()
