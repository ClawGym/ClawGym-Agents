#!/usr/bin/env python3
import sys
import os
import csv
# Reads vaccine inventory and flags any items below reorder point.
data_path = os.path.join(os.path.dirname(__file__), "..", "input", "inventory.csv")
data_path = os.path.normpath(data_path)
shortages = []
try:
    with open(data_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                item = (row.get("item", "") or "").strip()
                stock = int((row.get("stock", "") or "0").strip())
                reorder = int((row.get("reorder_point", "") or "0").strip())
            except Exception:
                sys.stderr.write(f"ERROR: bad row in {data_path}: {row}\n")
                sys.exit(3)
            if stock < reorder:
                shortages.append((item, stock, reorder))
except FileNotFoundError:
    sys.stderr.write(f"DATA ERROR: missing input file {data_path}\n")
    sys.exit(2)

if shortages:
    for item, stock, reorder in shortages:
        print(f"REORDER NEEDED: item={item}, stock={stock}, reorder_point={reorder}")
    sys.exit(1)
else:
    print("OK: all vaccine stocks above reorder point")
    sys.exit(0)
