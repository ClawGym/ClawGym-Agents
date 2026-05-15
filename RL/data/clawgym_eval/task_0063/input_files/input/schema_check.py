import sys, csv, argparse, collections

def main():
    parser = argparse.ArgumentParser(description="Simple CSV schema and duplicate checker")
    parser.add_argument('csv_path', help='Path to CSV file')
    parser.add_argument('--require', help='Comma-separated list of required columns', default='')
    args = parser.parse_args()

    req = [c.strip() for c in args.require.split(',') if c.strip()]

    try:
        with open(args.csv_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                print(f"ERROR: File appears empty: {args.csv_path}", file=sys.stderr)
                sys.exit(2)
            header_set = set(headers)
            missing = [c for c in req if c not in header_set]
            if missing:
                print("ERROR: Missing columns: " + ", ".join(missing), file=sys.stderr)
                sys.exit(2)
            rows = 0
            idx_player = headers.index('player_id') if 'player_id' in header_set else None
            counts = collections.Counter()
            for row in reader:
                rows += 1
                if idx_player is not None and len(row) > idx_player:
                    counts[row[idx_player]] += 1
            dups = {k: v for k, v in counts.items() if v > 1}
            print(f"OK: Header check passed for {args.csv_path}")
            print(f"INFO: Rows={rows}, Columns={len(headers)}")
            if idx_player is None:
                print("INFO: No player_id column present; duplicate check skipped")
            else:
                if dups:
                    parts = [f"{k} (count {v})" for k, v in sorted(dups.items())]
                    print("WARN: Duplicate player_id values detected: " + "; ".join(parts))
                else:
                    print("OK: No duplicate player_id values detected")
            sys.exit(0)
    except FileNotFoundError:
        print(f"ERROR: File not found: {args.csv_path}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: Exception during check: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == '__main__':
    main()
