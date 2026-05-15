import argparse
import json
import os
import re
import sys


def load_glossary(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    terms = []
    for t in data.get('terms', []):
        canonical = t.get('canonical', '').strip()
        syns = [s.strip() for s in t.get('synonyms', []) if s and s.strip()]
        if canonical and syns:
            terms.append({'canonical': canonical, 'synonyms': syns})
    return terms


def load_refs(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return set(data.get('refs', []))


def read_lines(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().splitlines()


def validate(md_path, glossary_path, refs_path):
    lines = read_lines(md_path)
    glossary = load_glossary(glossary_path)
    allowed_refs = load_refs(refs_path)

    errors = []
    warnings = []

    # Non-canonical terminology checks
    for term in glossary:
        canonical = term['canonical']
        for syn in term['synonyms']:
            # Case-insensitive, word-boundary match for the synonym
            pattern = re.compile(r"\\b" + re.escape(syn) + r"\\b", re.IGNORECASE)
            for i, line in enumerate(lines, start=1):
                for m in pattern.finditer(line):
                    errors.append({
                        'type': 'non_canonical_term',
                        'found': m.group(0),
                        'canonical': canonical,
                        'line': i
                    })

    # Citation key checks: [ref:some_key]
    cite_pattern = re.compile(r"\\[ref:([A-Za-z0-9_]+)\\]")
    for i, line in enumerate(lines, start=1):
        for m in cite_pattern.finditer(line):
            key = m.group(1)
            if key not in allowed_refs:
                errors.append({
                    'type': 'unknown_citation',
                    'key': key,
                    'line': i
                })

    result = {
        'file': md_path,
        'errors': errors,
        'warnings': warnings,
        'summary': {
            'error_count': len(errors),
            'warning_count': len(warnings)
        }
    }
    return result


def main():
    parser = argparse.ArgumentParser(description='Validate manuscript terminology and citations.')
    parser.add_argument('--in', dest='input_md', required=True, help='Path to input markdown file')
    parser.add_argument('--glossary', dest='glossary', required=True, help='Path to glossary.json')
    parser.add_argument('--refs', dest='refs', required=True, help='Path to refs.json')
    parser.add_argument('--out', dest='out', required=True, help='Path to output JSON report')
    args = parser.parse_args()

    report = validate(args.input_md, args.glossary, args.refs)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Also exit non-zero if there are errors to signal test failure semantics
    if report['summary']['error_count'] > 0:
        # Do not print; rely on JSON output for verification
        sys.exit(1)


if __name__ == '__main__':
    main()
