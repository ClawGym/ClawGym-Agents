import argparse
import csv
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Generate a Markdown checklist of required visa documents from a CSV.")
    parser.add_argument("csv", help="Path to visa checklist CSV")
    parser.add_argument("--out", required=True, help="Path to write Markdown checklist")
    args = parser.parse_args()

    # Read CSV (BUG: assumes ASCII)
    try:
        with open(args.csv, "r", encoding="ascii", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        sys.stderr.write(f"Failed to read CSV: {e}\n")
        raise

    # Filter required rows
    required_rows = []
    for row in rows:
        flag = str(row.get("required", "")).strip().lower() in ("yes", "y", "true", "1")
        if flag:
            required_rows.append(row)

    # Build Markdown lines
    lines = [f"Required documents ({len(required_rows)} items)", ""]
    for row in required_rows:
        doc = (row.get("document", "") or "").strip()
        deadline = (row.get("deadline", "") or "").strip()
        lines.append(f"- {doc} — deadline: {deadline}")

    # Write output (does not create parent dir)
    out_path = args.out
    with open(out_path, "w", encoding="utf-8") as out:
        out.write("\n".join(lines))


if __name__ == "__main__":
    main()
