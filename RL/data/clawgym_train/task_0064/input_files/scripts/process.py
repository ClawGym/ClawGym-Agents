#!/usr/bin/env python3
import csv
import os

def load_rows():
    # BUG: wrong directory and delimiter
    path = os.path.join("datas", "submissions.csv")
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        return list(reader)

def filter_completed(rows):
    # BUG: wrong column name and value check
    return [r for r in rows if r.get("completed") == "true"]

def score_key(row):
    # BUG: wrong column names and sort direction
    try:
        sc = int(row.get("score", "0"))
    except ValueError:
        sc = 0
    try:
        avg = float(row.get("avgMile", "0"))
    except ValueError:
        avg = 0.0
    # BUG: sorts ascending by default and wrong key order
    return (sc, avg, row.get("name", ""))

def rank(rows):
    sorted_rows = sorted(rows, key=score_key)  # BUG: should be opposite for score
    top = sorted_rows[:5]
    out = []
    for i, r in enumerate(top, start=1):
        out.append({
            "place": i,  # BUG: wrong header name
            "id": r.get("id"),
            "name": r.get("name"),
            "city": r.get("city"),
            "score": r.get("score"),  # BUG: wrong schema name
            "avgMile": r.get("avgMile")  # BUG: wrong schema name
        })
    return out

def write_out(rows):
    # BUG: wrong output directory and file name
    os.makedirs("outputs", exist_ok=True)
    out_path = os.path.join("outputs", "top.csv")
    with open(out_path, "w", newline="") as f:
        fieldnames = ["place", "id", "name", "city", "score", "avgMile"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

if __name__ == "__main__":
    rows = load_rows()
    rows = filter_completed(rows)
    ranked = rank(rows)
    write_out(ranked)
    print("Wrote outputs/top.csv")
