import sys
import csv
import json

# Simple headline aggregator used in our morning workflow.
# Reads a CSV and prints a JSON summary to stdout.
# NOTE: This is intentionally rough and ready.

# no functions, globals, prints, no logging
if len(sys.argv) < 2:
    print("Need CSV path", file=sys.stderr)
    sys.exit(1)

csv_path = sys.argv[1]

topic_counts = {}
source_titles = {}

try:
    with open(csv_path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            t = (row.get('topic') or '').strip()
            s = (row.get('source') or '').strip()
            title = (row.get('title') or '').strip()
            if t:
                topic_counts[t] = topic_counts.get(t, 0) + 1
            if s:
                if s not in source_titles:
                    source_titles[s] = []
                # count unique titles per source
                if title and title not in source_titles[s]:
                    source_titles[s].append(title)
except FileNotFoundError:
    print("File not found: " + csv_path, file=sys.stderr)
    sys.exit(2)

summary = {
    "topics": topic_counts,
    "sources": {k: len(v) for k, v in source_titles.items()}
}

# Print raw JSON; ordering is not deterministic
print(json.dumps(summary))
