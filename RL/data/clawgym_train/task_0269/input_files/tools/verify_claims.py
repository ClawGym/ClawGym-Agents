import os
import csv
import json
from typing import Dict, List, Any, Tuple

CONFIG_PATH = os.path.join('config', 'fields.json')
CATALOG_PATH = os.path.join('input', 'boyds_catalog.csv')
CLAIMS_PATH = os.path.join('input', 'claims_to_verify.jsonl')
OUTPUT_DIR = 'output'
REPORT_PATH = os.path.join(OUTPUT_DIR, 'verification_report.json')
SUMMARY_PATH = os.path.join(OUTPUT_DIR, 'summary.txt')


def load_config(path: str) -> Dict[str, str]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_catalog(path: str, fieldmap: Dict[str, str]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    sku_key = fieldmap['sku_field']
    title_key = fieldmap['title_field']
    intro_key = fieldmap['intro_year_field']
    retire_key = fieldmap['retire_year_field']
    line_key = fieldmap['line_field']

    by_sku: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[str, Dict[str, Any]] = {}

    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get(sku_key) or '').strip()
            title = (row.get(title_key) or '').strip()
            intro_year_raw = (row.get(intro_key) or '').strip()
            retire_year_raw = (row.get(retire_key) or '').strip()
            line_val = (row.get(line_key) or '').strip()

            def parse_int_or_none(s: str):
                s = s.strip()
                if s == '':
                    return None
                try:
                    return int(s)
                except ValueError:
                    return None

            record = {
                'sku': sku,
                'title': title,
                'intro_year': parse_int_or_none(intro_year_raw),
                'retire_year': parse_int_or_none(retire_year_raw),
                'line': line_val
            }
            if sku:
                by_sku[sku] = record
            if title:
                by_title[title.lower()] = record
    return by_sku, by_title


def load_claims(path: str) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            claims.append(json.loads(line))
    return claims


def verify_claim(claim: Dict[str, Any], by_sku: Dict[str, Dict[str, Any]], by_title: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    claim_id = claim.get('claim_id')
    sku = claim.get('sku')
    title = claim.get('title')

    record = None
    match_key = None

    if sku:
        record = by_sku.get(str(sku))
        match_key = 'sku'
    elif title:
        record = by_title.get(title.lower())
        match_key = 'title'
    else:
        return {
            'claim_id': claim_id,
            'match_key': None,
            'status': 'insufficient',
            'mismatched_fields': [],
            'evidence': None
        }

    if record is None:
        return {
            'claim_id': claim_id,
            'match_key': match_key,
            'status': 'not_found',
            'mismatched_fields': [],
            'evidence': None
        }

    mismatches = []

    # Compare intro year
    if 'claimed_intro_year' in claim:
        claimed_intro = claim['claimed_intro_year']
        rec_intro = record.get('intro_year')
        if rec_intro != claimed_intro:
            mismatches.append('intro_year')

    # Compare retire year (None in catalog vs provided claim -> mismatch)
    if 'claimed_retire_year' in claim:
        claimed_retire = claim['claimed_retire_year']
        rec_retire = record.get('retire_year')
        if rec_retire != claimed_retire:
            mismatches.append('retire_year')

    # Compare line (case-insensitive)
    if 'claimed_line' in claim:
        claimed_line = (claim['claimed_line'] or '').strip().lower()
        rec_line = (record.get('line') or '').strip().lower()
        if rec_line != claimed_line:
            mismatches.append('line')

    status = 'supported' if len(mismatches) == 0 else 'contradicted'

    return {
        'claim_id': claim_id,
        'match_key': match_key,
        'status': status,
        'mismatched_fields': mismatches,
        'evidence': {
            'sku': record.get('sku'),
            'title': record.get('title'),
            'intro_year': record.get('intro_year'),
            'retire_year': record.get('retire_year'),
            'line': record.get('line')
        }
    }


def write_outputs(results: List[Dict[str, Any]]) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    counts: Dict[str, int] = {}
    for r in results:
        counts[r['status']] = counts.get(r['status'], 0) + 1

    lines = []
    for key in ['supported', 'contradicted', 'not_found', 'insufficient']:
        lines.append(f"{key}: {counts.get(key, 0)}")
    with open(SUMMARY_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def main() -> None:
    fieldmap = load_config(CONFIG_PATH)
    by_sku, by_title = load_catalog(CATALOG_PATH, fieldmap)
    claims = load_claims(CLAIMS_PATH)
    results = [verify_claim(c, by_sku, by_title) for c in claims]
    write_outputs(results)


if __name__ == '__main__':
    main()
