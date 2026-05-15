import csv
import os

# Very quick script my nephew wrote. It only reads one file and sorts yields as strings.
DATA_FILE = "input/crop_yields_2022.csv"

rows = []
f = open(DATA_FILE, "r", encoding="utf-8")
reader = csv.DictReader(f)
for r in reader:
    rows.append(r)
f.close()

# duplicated read of the same file (buggy)
more = []
f2 = open(DATA_FILE, "r", encoding="utf-8")
reader2 = csv.DictReader(f2)
for r in reader2:
    more.append(r)
f2.close()

rows = rows + more

# sorts by yield but as string, not number
def bad_sort(items):
    return sorted(items, key=lambda x: x.get("yield_kg", "0"), reverse=True)

top = bad_sort(rows)

print("Top yields (string-sorted) from", DATA_FILE)
for r in top:
    print(r.get("crop"), r.get("yield_kg"))

# TODO: future: read more files, filter by crop, maybe fetch co-op website
