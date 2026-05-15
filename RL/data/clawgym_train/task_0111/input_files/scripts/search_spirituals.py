import argparse
import json
import csv
import sys
import os
from typing import List, Dict

# Simple JSONL corpus scanner. Expects a JSON config with keys:
#   keywords: list of strings
#   fields: list of JSON fields to scan (e.g., ["title", "text"])
#   start_year: int (inclusive)
#   end_year: int (inclusive)
#   case_sensitive: bool
# Usage:
#   python3 scripts/search_spirituals.py --config config/search_config.json --input input/sources/spirituals_corpus.jsonl --output output/matches.csv

def load_config(path: str) -> Dict:
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    # Intentionally strict: require keys so misnamed config fails loudly
    if 'keywords' not in cfg or 'fields' not in cfg:
        missing = [k for k in ['keywords', 'fields'] if k not in cfg]
        raise KeyError(f"Missing required config key(s): {', '.join(missing)}")
    # Types sanity check
    if not isinstance(cfg['keywords'], list) or not all(isinstance(x, str) for x in cfg['keywords']):
        raise TypeError("config['keywords'] must be a list of strings")
    if not isinstance(cfg['fields'], list) or not all(isinstance(x, str) for x in cfg['fields']):
        raise TypeError("config['fields'] must be a list of strings")
    return cfg


def scan_record(rec: Dict, keywords: List[str], fields: List[str], case_sensitive: bool) -> List[Dict]:
    matches = []
    for field in fields:
        text = rec.get(field, '')
        if not isinstance(text, str):
            continue
        base = text if case_sensitive else text.lower()
        for kw in keywords:
            target = kw if case_sensitive else kw.lower()
            idx = base.find(target)
            if idx != -1:
                start = max(0, idx - 40)
                end = min(len(text), idx + len(kw) + 40)
                excerpt = ('' if start == 0 else '...') + text[start:end] + ('' if end == len(text) else '...')
                matches.append({
                    'id': rec.get('id', ''),
                    'title': rec.get('title', ''),
                    'year': rec.get('year', ''),
                    'movement_type': rec.get('movement_type', ''),
                    'field': field,
                    'keyword': kw,
                    'match_start': idx,
                    'match_excerpt': excerpt
                })
    return matches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except Exception as e:
        sys.stderr.write(f"Config error: {e}\n")
        sys.exit(2)

    keywords = cfg['keywords']
    fields = cfg['fields']
    start_year = int(cfg.get('start_year', -10**9))
    end_year = int(cfg.get('end_year', 10**9))
    case_sensitive = bool(cfg.get('case_sensitive', False))

    total = 0
    hits = 0
    out_dir = os.path.dirname(args.output)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(args.input, 'r', encoding='utf-8') as fin, open(args.output, 'w', encoding='utf-8', newline='') as fout:
        writer = csv.DictWriter(fout, fieldnames=['id','title','year','movement_type','field','keyword','match_start','match_excerpt'])
        writer.writeheader()
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                sys.stderr.write(f"Skipping malformed JSONL line: {e}\n")
                continue
            total += 1
            year = rec.get('year', None)
            try:
                y = int(year)
            except Exception:
                y = None
            if y is not None and (y < start_year or y > end_year):
                continue
            rec_matches = scan_record(rec, keywords, fields, case_sensitive)
            for m in rec_matches:
                writer.writerow(m)
            hits += len(rec_matches)
    sys.stdout.write(f"Processed {total} records; found {hits} matches.\n")

if __name__ == '__main__':
    main()
