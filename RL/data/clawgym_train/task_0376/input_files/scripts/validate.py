#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from datetime import datetime


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def ensure_parent_dir(path):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def validate_record(rec, cfg):
    issues = []

    def add_issue(field, code, msg):
        issues.append({
            'field': field,
            'code': code,
            'message': msg
        })

    # Required fields
    for field in cfg.get('required_fields', []):
        if field not in rec:
            add_issue(field, 'MISSING_FIELD', f"Missing required field {field}")

    # Only continue field-specific checks if fields are present
    # Title
    if 'title' in rec:
        if not isinstance(rec['title'], str) or not rec['title'].strip():
            add_issue('title', 'EMPTY_TITLE', 'Title must be a non-empty string')

    # Date format
    if 'date' in rec:
        date_regex = cfg.get('date_regex')
        if date_regex:
            if not re.match(date_regex, str(rec['date'])):
                add_issue('date', 'DATE_FORMAT', 'Invalid date format, expected YYYY-MM-DD')

    # URL format
    if 'url' in rec:
        url_regex = cfg.get('url_regex')
        if url_regex:
            if not re.match(url_regex, str(rec['url'])):
                add_issue('url', 'URL_FORMAT', 'Invalid URL format, expected http(s)://')

    # Tags
    if 'tags' in rec:
        tags = rec['tags']
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            add_issue('tags', 'TAGS_TYPE', 'Tags must be a list of strings')
        else:
            if len(tags) == 0:
                add_issue('tags', 'TAGS_EMPTY', 'Tags list must not be empty')
            allowed = set(cfg.get('allowed_tags', []))
            unknown = [t for t in tags if t not in allowed]
            if unknown:
                add_issue('tags', 'TAG_UNKNOWN', f"Unknown tag(s): {', '.join(unknown)}")

    status = 'pass' if len(issues) == 0 else 'fail'
    return status, issues


def main():
    p = argparse.ArgumentParser(description='Validate exhibits metadata against a simple schema')
    p.add_argument('--input', required=True, help='Path to exhibits JSON file')
    p.add_argument('--schema', required=True, help='Path to config JSON file')
    p.add_argument('--out', required=True, help='Path to write validation report JSON')
    args = p.parse_args()

    try:
        cfg = load_json(args.schema)
    except Exception as e:
        print(f"Error loading schema: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        data = load_json(args.input)
    except Exception as e:
        print(f"Error loading input: {e}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(data, list):
        print('Input must be a JSON array of exhibit records', file=sys.stderr)
        sys.exit(2)

    checks = []
    passed = 0
    failed = 0

    for rec in data:
        rec_id = rec.get('id', '(no-id)')
        rec_title = rec.get('title', '(no-title)')
        status, issues = validate_record(rec, cfg)
        if status == 'pass':
            passed += 1
        else:
            failed += 1
        checks.append({
            'id': rec_id,
            'title': rec_title,
            'status': status,
            'issues': issues
        })

    report = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'summary': {
            'total': len(data),
            'passed': passed,
            'errors': failed,
            'warnings': 0
        },
        'checks': checks
    }

    ensure_parent_dir(args.out)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Also print a brief summary to stdout for convenience
    s = report['summary']
    print(f"Validation complete: total={s['total']} passed={s['passed']} failed={s['errors']} warnings={s['warnings']}")


if __name__ == '__main__':
    main()
