import argparse
import csv
import json
import os
import re
import sys
from typing import Dict, List, Optional


def load_schema(path: str) -> Dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_cities_mapping(default_path: str = 'input/cities.csv') -> Dict[str, str]:
    mapping = {}
    if os.path.exists(default_path):
        try:
            with open(default_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    city = row.get('city')
                    country = row.get('country')
                    if city and country:
                        mapping[city] = country
        except Exception:
            pass
    return mapping


def validate(input_path: str, schema_path: str) -> int:
    schema = load_schema(schema_path)
    cities = load_cities_mapping()

    required_fields = schema.get('required_fields', [])
    id_prefix = schema.get('id_prefix', '')
    id_digits = schema.get('id_digits', 0)
    date_regex = schema.get('date_regex', r'^\\d{4}-\\d{2}-\\d{2}$')

    id_pattern = re.compile(r'^' + re.escape(id_prefix) + r'\d{' + str(id_digits) + r'}$')
    date_pattern = re.compile(date_regex)

    errors: List[Dict] = []
    records: List[Dict] = []
    id_to_lines: Dict[str, List[int]] = {}

    total_lines = 0

    with open(input_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, start=1):
            total_lines += 1
            line = line.strip()
            if not line:
                errors.append({
                    'line_number': i,
                    'record_id': None,
                    'message': 'Empty line'
                })
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append({
                    'line_number': i,
                    'record_id': None,
                    'message': f'JSON parse error: {str(e)}'
                })
                continue

            rec_id = obj.get('id')
            # Required fields
            for field in required_fields:
                val = obj.get(field)
                if val is None or (isinstance(val, str) and val.strip() == ''):
                    msg = f"'{field}' is missing or empty"
                    # Suggest country from city when possible
                    if field == 'country':
                        city = obj.get('city')
                        if city and city in cities:
                            msg += f"; hint: for city '{city}', country is '{cities[city]}'"
                    errors.append({
                        'line_number': i,
                        'record_id': rec_id,
                        'message': msg
                    })

            # ID pattern
            if rec_id is not None:
                if not id_pattern.match(str(rec_id)):
                    errors.append({
                        'line_number': i,
                        'record_id': rec_id,
                        'message': f"id '{rec_id}' does not match pattern {id_prefix}<{'{'}digits{'}'} where digits={id_digits}"
                    })
                id_to_lines.setdefault(rec_id, []).append(i)

            # Date format
            date_val = obj.get('date')
            if date_val is not None and not date_pattern.match(str(date_val)):
                errors.append({
                    'line_number': i,
                    'record_id': rec_id,
                    'message': f"date format invalid: expected YYYY-MM-DD, got '{date_val}'"
                })

            records.append({'line_number': i, 'id': rec_id})

    # Duplicate ID checks
    for rid, lines in id_to_lines.items():
        if rid is not None and len(lines) > 1:
            errors.append({
                'line_number': lines[1],
                'record_id': rid,
                'message': f"duplicate id '{rid}' also appears on line {lines[0]}"
            })

    if errors:
        print(f"Validation failed with {len(errors)} error(s) across {total_lines} line(s). Details:")
        for e in errors:
            ln = e.get('line_number')
            rid = e.get('record_id')
            msg = e.get('message')
            rid_str = rid if rid is not None else 'n/a'
            print(f"Error: line {ln} (id={rid_str}): {msg}")
        return 1
    else:
        print(f"Validation passed: {len(records)} record(s) validated.")
        return 0


def main():
    parser = argparse.ArgumentParser(description='Validate transcript JSONL against schema and basic rules.')
    parser.add_argument('--input', required=True, help='Path to the JSONL file')
    parser.add_argument('--schema', required=True, help='Path to the schema JSON')
    args = parser.parse_args()

    rc = validate(args.input, args.schema)
    sys.exit(rc)


if __name__ == '__main__':
    main()
