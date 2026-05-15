import sys, csv, re
from datetime import datetime

REQ_FIELDS = ["series","season","episode","title","genre","character","character_role","watched_date","rating"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def err(path, line_num, msg):
    sys.stderr.write(f"ERROR in {path} on line {line_num}: {msg}\n")

def validate_csv(path):
    errors = 0
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            # Header is line 1; first data row is line 2
            for i, row in enumerate(reader, start=2):
                # Required fields non-empty
                for key in REQ_FIELDS:
                    if row.get(key) is None or str(row.get(key)).strip() == "":
                        errors += 1
                        err(path, i, f"missing required field '{key}'")
                        break  # avoid cascading checks on an empty row
                else:
                    # Genre must be Western
                    if row["genre"].strip() != "Western":
                        errors += 1
                        err(path, i, f"invalid genre '{row['genre']}' (expected 'Western')")
                        continue
                    # Season and episode must be positive integers
                    try:
                        season = int(row["season"]) ; episode = int(row["episode"])
                        if season <= 0 or episode <= 0:
                            raise ValueError("non-positive season/episode")
                    except Exception:
                        errors += 1
                        err(path, i, "season/episode must be positive integers")
                        continue
                    # Rating must be integer 1..10
                    try:
                        rating = int(row["rating"]) ;
                        if rating < 1 or rating > 10:
                            raise ValueError("out of range")
                    except Exception:
                        errors += 1
                        err(path, i, f"invalid rating '{row['rating']}' (expected 1..10)")
                        continue
                    # Date format YYYY-MM-DD
                    if not DATE_RE.match(row["watched_date"].strip()):
                        errors += 1
                        err(path, i, f"invalid watched_date '{row['watched_date']}' (expected YYYY-MM-DD)")
                        continue
                    try:
                        datetime.strptime(row["watched_date"].strip(), "%Y-%m-%d")
                    except Exception:
                        errors += 1
                        err(path, i, f"invalid watched_date '{row['watched_date']}' (not a real date)")
                        continue
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: file not found: {path}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"ERROR: failed to process {path}: {e}\n")
        return 1
    if errors == 0:
        sys.stdout.write(f"OK: {path}\n")
        return 0
    else:
        sys.stdout.write(f"SUMMARY: {errors} errors in {path}\n")
        return 1

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: python tools/validate_watchlog.py <csv_path>\n")
        sys.exit(2)
    sys.exit(validate_csv(sys.argv[1]))
