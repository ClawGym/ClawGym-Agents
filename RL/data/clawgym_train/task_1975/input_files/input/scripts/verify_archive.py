#!/usr/bin/env python3
import sys
import argparse
import csv
import json
from collections import OrderedDict

def parse_args():
    p = argparse.ArgumentParser(description="Verify archive integrity by comparing catalog and inventory.")
    p.add_argument("--catalog", required=True, help="Path to catalog CSV with headers id,path,size_bytes,checksum_sha256")
    p.add_argument("--inventory", required=True, help="Path to inventory JSON mapping path->checksum_sha256")
    return p.parse_args()

def read_catalog(path):
    catalog = OrderedDict()
    with open(path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            p = row["path"].strip()
            catalog[p] = {
                "checksum": row["checksum_sha256"].strip(),
                "size": int(row["size_bytes"].strip()) if row.get("size_bytes") else None,
                "id": row.get("id", "").strip()
            }
    return catalog

def read_inventory(path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    # Expect a mapping of path->checksum
    inv = {}
    for k, v in data.items():
        inv[str(k).strip()] = str(v).strip()
    return inv

def main():
    args = parse_args()
    try:
        catalog = read_catalog(args.catalog)
        inventory = read_inventory(args.inventory)
    except Exception as e:
        print(f"ERROR: failed to read inputs: {e}", file=sys.stderr)
        sys.exit(3)

    cat_paths = set(catalog.keys())
    inv_paths = set(inventory.keys())

    missing = sorted(list(cat_paths - inv_paths))
    unknown = sorted(list(inv_paths - cat_paths))

    mismatched = []
    ok = []
    for p in sorted(cat_paths & inv_paths):
        exp = catalog[p]["checksum"]
        got = inventory[p]
        if exp != got:
            mismatched.append((p, exp, got))
        else:
            ok.append(p)

    expected = len(catalog)
    present = len(ok) + len(mismatched)

    print(f"SUMMARY: expected={expected} present={present} ok={len(ok)} missing={len(missing)} mismatched={len(mismatched)} unknown={len(unknown)}")

    if missing:
        print("DETAILS: MISSING")
        for p in missing:
            print(f"- MISSING: {p}")
    if mismatched:
        print("DETAILS: CHECKSUM_MISMATCH")
        for p, exp, got in mismatched:
            print(f"- MISMATCH: {p} expected={exp} got={got}")
    if unknown:
        print("DETAILS: UNKNOWN_NOT_IN_CATALOG")
        for p in unknown:
            print(f"- UNKNOWN: {p}")

    # Exit codes: 0=clean, 2=issues found, 3=input error
    sys.exit(0 if not missing and not mismatched else 2)

if __name__ == "__main__":
    main()
