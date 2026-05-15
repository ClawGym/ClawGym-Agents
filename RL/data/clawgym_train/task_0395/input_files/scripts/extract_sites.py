#!/usr/bin/env python3
import argparse
import json
import os
import sys
from html.parser import HTMLParser

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_th = False
        self.in_td = False
        self.in_tr = False
        self.in_thead = False
        self.in_tbody = False
        self.headers = None
        self.current_cells = []
        self.rows = []
        self._cell_data = []

    def handle_starttag(self, tag, attrs):
        if tag == 'thead':
            self.in_thead = True
        elif tag == 'tbody':
            self.in_tbody = True
        elif tag == 'tr':
            self.in_tr = True
            self.current_cells = []
        elif tag == 'th':
            self.in_th = True
            self._cell_data = []
        elif tag == 'td':
            self.in_td = True
            self._cell_data = []

    def handle_data(self, data):
        if self.in_th or self.in_td:
            self._cell_data.append(data)

    def handle_endtag(self, tag):
        if tag == 'th':
            text = ''.join(self._cell_data).strip()
            self.current_cells.append(text)
            self.in_th = False
        elif tag == 'td':
            text = ''.join(self._cell_data).strip()
            self.current_cells.append(text)
            self.in_td = False
        elif tag == 'tr':
            if self.in_thead and self.current_cells:
                self.headers = [self._normalize_header(h) for h in self.current_cells]
            elif self.in_tbody and self.current_cells:
                self.rows.append(self.current_cells[:])
            self.in_tr = False
        elif tag == 'thead':
            self.in_thead = False
        elif tag == 'tbody':
            self.in_tbody = False

    @staticmethod
    def _normalize_header(h):
        key = h.strip().lower()
        mapping = {
            'name': 'name',
            'city': 'city',
            'style': 'style',
            'period': 'period'
        }
        return mapping.get(key, key)


def parse_args():
    p = argparse.ArgumentParser(description='Extract site table into JSON.')
    p.add_argument('--input', '-i', required=True, help='Path to input HTML file')
    p.add_argument('--out', '-o', required=True, help='Path to output JSON file')
    return p.parse_args()


def main():
    args = parse_args()
    html_path = args.input
    out_path = args.out

    if not os.path.isfile(html_path):
        print(f"ERROR: input file not found: {html_path}", file=sys.stderr)
        sys.exit(1)

    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    parser = TableParser()
    parser.feed(html)

    if not parser.headers:
        print("ERROR: No table headers found", file=sys.stderr)
        sys.exit(2)

    # Ensure expected headers are present
    expected = ['name', 'city', 'style', 'period']
    missing_headers = [h for h in expected if h not in parser.headers]
    if missing_headers:
        print(f"ERROR: Missing expected headers: {', '.join(missing_headers)}", file=sys.stderr)
        sys.exit(3)

    # Map rows to dicts
    header_indices = {h: i for i, h in enumerate(parser.headers)}
    records = []
    for idx, cells in enumerate(parser.rows):
        rec = {}
        for h in expected:
            i = header_indices.get(h)
            value = cells[i].strip() if i is not None and i < len(cells) else ''
            rec[h] = value
        name_display = rec.get('name') or f'row {idx+1}'
        missing_fields = [k for k in expected if not rec.get(k, '').strip()]
        for mf in missing_fields:
            print(f"WARNING: missing '{mf}' for '{name_display}'", file=sys.stderr)
        records.append(rec)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"INFO: Parsed {len(records)} site(s)")
    print(f"INFO: Wrote JSON to {out_path}")

if __name__ == '__main__':
    main()
