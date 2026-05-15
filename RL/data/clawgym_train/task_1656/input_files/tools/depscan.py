import argparse
import json
import sys
from typing import Dict, List


def parse_requirements(path: str) -> Dict[str, str]:
    pkgs = {}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '==' not in line:
                continue
            name, version = line.split('==', 1)
            name = name.strip()
            version = version.strip()
            pkgs[name] = version
    return pkgs


def load_db(path: str) -> Dict[str, Dict[str, List[dict]]]:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # normalize keys to lowercase for matching
    norm = {}
    for pkg, versions in data.items():
        norm[pkg.lower()] = {}
        for ver, vulns in versions.items():
            norm[pkg.lower()][ver] = vulns
    return norm


def scan(requirements: Dict[str, str], db: Dict[str, Dict[str, List[dict]]]) -> dict:
    findings = []
    packages_with_vulns = set()
    for pkg, ver in requirements.items():
        vulns_for_pkg = db.get(pkg.lower(), {})
        vulns_for_ver = vulns_for_pkg.get(ver, [])
        for v in vulns_for_ver:
            findings.append({
                'package': pkg,
                'version': ver,
                'cve_id': v.get('id'),
                'severity': v.get('severity'),
                'fixed_in': v.get('fixed_in')
            })
            packages_with_vulns.add(pkg)
    report = {
        'summary': {
            'total_packages': len(requirements),
            'packages_with_vulns': len(packages_with_vulns),
            'total_findings': len(findings)
        },
        'findings': findings,
        'requirements': requirements
    }
    return report


def main():
    ap = argparse.ArgumentParser(description='Offline dependency vulnerability scan (local DB).')
    ap.add_argument('--requirements', required=True, help='Path to requirements.txt')
    ap.add_argument('--db', required=True, help='Path to vulnerabilities.json')
    ap.add_argument('--out', required=True, help='Path to write JSON report')
    args = ap.parse_args()
    reqs = parse_requirements(args.requirements)
    db = load_db(args.db)
    report = scan(reqs, db)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, sort_keys=True)
    print(f"Wrote report to {args.out}")


if __name__ == '__main__':
    sys.exit(main())
