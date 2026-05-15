import argparse
import json
import os
import sys
from typing import List, Dict


def load_rules(config_path: str) -> Dict:
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _normalize(s: str) -> str:
    return s.lower()


def find_avoid_terms(text: str, avoid_terms: List[str]) -> List[str]:
    text_norm = _normalize(text)
    found = set()
    for term in avoid_terms:
        t = _normalize(term)
        if t and t in text_norm:
            found.add(term)
    return sorted(found, key=lambda x: x.lower())


def check_text(text: str, rules: Dict) -> Dict:
    avoid_terms = rules.get('avoid_terms', [])
    violations = find_avoid_terms(text, avoid_terms)
    return {
        'violations': violations,
        'ok': len(violations) == 0
    }


def check_file(file_path: str, rules: Dict) -> Dict:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    result = check_text(content, rules)
    result['file'] = file_path
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check text files against avoid_terms rules.')
    parser.add_argument('--check', dest='check_path', required=True, help='Path to a text/markdown file to check')
    parser.add_argument('--config', dest='config_path', default=os.path.join('config', 'style_rules.json'), help='Path to style rules JSON')
    args = parser.parse_args(argv)

    rules = load_rules(args.config_path)
    report = check_file(args.check_path, rules)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
