#!/usr/bin/env python3
import sys
import json
import csv

def main():
    if len(sys.argv) != 2:
        print("ERROR: usage: incident_parser.py <path_to_jsonl>", file=sys.stderr)
        return 2
    path = sys.argv[1]
    rows = []
    errors = 0
    warns = 0
    total = 0
    required = ["plant", "date", "type", "severity", "status", "summary"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                total += 1
                line = line.strip()
                if not line:
                    # Skip empty lines
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    errors += 1
                    print(f"ERROR line {i}: invalid JSON", file=sys.stderr)
                    continue
                for k in required:
                    if k not in obj:
                        warns += 1
                        print(f"WARN line {i}: missing field {k}", file=sys.stderr)
                        obj.setdefault(k, "")
                rows.append([obj["plant"], obj["date"], obj["type"], obj["severity"], obj["status"], obj["summary"]])
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1
    # Write CSV to stdout
    w = csv.writer(sys.stdout)
    w.writerow(["plant", "date", "type", "severity", "status", "summary"])
    for r in rows:
        w.writerow(r)
    # Diagnostics to stderr
    print(f"INFO: parsed_records={len(rows)} total_lines={total} errors={errors} warnings={warns}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
