import csv
import argparse
import os

HTML_HEADER = "<html><head><meta charset='utf-8'><title>Weekly Market Digest</title></head><body><h1>Weekly Market Digest</h1><ul>"
HTML_FOOTER = "</ul></body></html>"

def build_html(rows):
    items = []
    for r in rows:
        date = (r.get('date') or '').strip()
        headline = (r.get('headline') or '').strip()
        summary = (r.get('summary') or '').strip()
        items.append(f"<li><strong>{date} — {headline}</strong><br>{summary}</li>")
    return HTML_HEADER + "\n".join(items) + HTML_FOOTER

def main():
    parser = argparse.ArgumentParser(description='Build the weekly market digest HTML from a CSV file.')
    parser.add_argument('-i', '--input', required=True, help='Path to input CSV (with headers: date, headline, summary)')
    parser.add_argument('-o', '--output', required=True, help='Path to output HTML file (e.g., dist/digest.html)')
    args = parser.parse_args()

    with open(args.input, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    html = build_html(rows)
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as out:
        out.write(html)
    print(f"Wrote {args.output} ({len(rows)} items)")

if __name__ == '__main__':
    main()
