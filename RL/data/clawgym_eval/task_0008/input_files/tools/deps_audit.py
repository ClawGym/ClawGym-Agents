#!/usr/bin/env python3
import argparse
import json
import os
import sys


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=False)


def main():
    parser = argparse.ArgumentParser(description='Simple dependency vulnerability auditor (exact-version match).')
    parser.add_argument('--deps', required=True, help='Path to dependencies.json')
    parser.add_argument('--db', required=True, help='Path to vuln_db.json')
    parser.add_argument('--out', required=True, help='Path to write scan_results.json')
    args = parser.parse_args()

    try:
        deps = load_json(args.deps)
        db = load_json(args.db)
    except Exception as e:
        print(f'Error reading inputs: {e}', file=sys.stderr)
        sys.exit(2)

    vulns = []
    # Build an index of vulnerabilities by package for faster lookup
    db_by_pkg = {}
    for entry in db:
        pkg = entry.get('package')
        db_by_pkg.setdefault(pkg, []).append(entry)

    for dep in deps:
        name = dep.get('name')
        version = dep.get('version')
        for entry in db_by_pkg.get(name, []):
            affected = entry.get('affected_versions', [])
            if version in affected:
                vulns.append({
                    'package': name,
                    'version': version,
                    'id': entry.get('id'),
                    'severity': entry.get('severity'),
                    'title': entry.get('title')
                })

    # Deterministic ordering
    vulns.sort(key=lambda v: (v.get('package', ''), v.get('id', '')))

    sev_counts = {'High': 0, 'Medium': 0, 'Low': 0}
    for v in vulns:
        sev = v.get('severity', 'Unknown')
        if sev not in sev_counts:
            sev_counts[sev] = 0
        sev_counts[sev] += 1

    result = {
        'vulnerabilities': vulns,
        'severity_counts': sev_counts,
        'total': len(vulns)
    }

    try:
        write_json(args.out, result)
    except Exception as e:
        print(f'Error writing output: {e}', file=sys.stderr)
        sys.exit(3)

    print(f'Wrote {args.out} with {len(vulns)} findings')


if __name__ == '__main__':
    main()
