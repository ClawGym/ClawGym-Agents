import argparse
import csv
import json
import os


def validate(catalog_path):
    items = []
    with open(catalog_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            items.append(row)

    details = []
    ok = 0
    mismatched = 0
    missing = 0

    for row in items:
        fid = (row.get("id") or "").strip()
        fpath = (row.get("file_path") or "").strip()
        exp_raw = (row.get("expected_size") or "").strip()
        try:
            expected = int(exp_raw)
        except Exception:
            expected = None

        if not os.path.exists(fpath):
            details.append({
                "id": fid,
                "file_path": fpath,
                "expected_size": expected,
                "actual_size": None,
                "status": "missing"
            })
            missing += 1
            continue

        with open(fpath, "rb") as fh:
            data = fh.read()
        actual = len(data)

        status = "ok"
        if expected is None:
            # If no expected size provided, treat as ok but include actual for transparency
            status = "ok"
        elif actual != expected:
            status = "mismatch"

        if status == "ok":
            ok += 1
        elif status == "mismatch":
            mismatched += 1

        details.append({
            "id": fid,
            "file_path": fpath,
            "expected_size": expected,
            "actual_size": actual,
            "status": status
        })

    return {
        "total_items": len(items),
        "ok": ok,
        "mismatched": mismatched,
        "missing": missing,
        "details": details
    }


def main():
    parser = argparse.ArgumentParser(description="Validate file sizes against catalog")
    parser.add_argument("--catalog", required=True, help="Path to catalog CSV with columns: id,file_path,expected_size")
    parser.add_argument("--out", required=True, help="Path to write JSON validation results")
    args = parser.parse_args()

    results = validate(args.catalog)
    out_dir = os.path.dirname(args.out)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
