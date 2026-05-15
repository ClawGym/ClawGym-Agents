#!/usr/bin/env python3
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from collections import Counter


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Validate puzzles against story scenes.")
    parser.add_argument('puzzles', help='Path to puzzles.json')
    parser.add_argument('scenes', help='Path to story_scenes.json')
    parser.add_argument('--out', required=True, help='Path to write validation_report.json')
    args = parser.parse_args()

    puzzles = load_json(args.puzzles)
    scenes = load_json(args.scenes)

    allowed_types = {"riddle", "maze", "cipher"}
    allowed_difficulties = {"easy", "medium", "hard"}
    id_pattern = re.compile(r'^PZ-\d{3}$')

    issues = []
    seen_ids = {}

    # Validate puzzles
    for idx, p in enumerate(puzzles):
        pid = p.get('id')
        ptype = p.get('type')
        pdiff = p.get('difficulty')
        pans = p.get('answer')

        if not isinstance(pid, str) or not id_pattern.match(pid):
            issues.append({
                'category': 'id_invalid_format',
                'puzzle_id': pid,
                'scene_id': None,
                'message': f"puzzle id '{pid}' does not match required pattern PZ-###"
            })

        if ptype not in allowed_types:
            issues.append({
                'category': 'invalid_type',
                'puzzle_id': pid,
                'scene_id': None,
                'message': f"puzzle '{pid}' has invalid type '{ptype}'"
            })

        if pdiff not in allowed_difficulties:
            issues.append({
                'category': 'invalid_difficulty',
                'puzzle_id': pid,
                'scene_id': None,
                'message': f"puzzle '{pid}' has invalid difficulty '{pdiff}'"
            })

        # Riddle answer rule: lowercase letters only (no spaces)
        if ptype == 'riddle':
            if not isinstance(pans, str) or re.fullmatch(r'[a-z]+', pans) is None:
                issues.append({
                    'category': 'answer_format',
                    'puzzle_id': pid,
                    'scene_id': None,
                    'message': f"riddle '{pid}' answer should be lowercase letters only"
                })

        # Duplicate ID detection (flag every occurrence after the first)
        if pid in seen_ids:
            first_idx = seen_ids[pid]
            issues.append({
                'category': 'duplicate_id',
                'puzzle_id': pid,
                'scene_id': None,
                'message': f"duplicate puzzle id '{pid}' also seen at index {first_idx}"
            })
        else:
            seen_ids[pid] = idx

    existing_ids = set(seen_ids.keys())

    # Validate scene references
    for s in scenes:
        sid = s.get('id')
        for ref in s.get('puzzles', []):
            if ref not in existing_ids:
                issues.append({
                    'category': 'missing_reference',
                    'puzzle_id': ref,
                    'scene_id': sid,
                    'message': f"scene '{sid}' references unknown puzzle id '{ref}'"
                })

    counts = Counter(i['category'] for i in issues)

    report = {
        'input': {
            'puzzles': args.puzzles,
            'scenes': args.scenes
        },
        'summary': {
            'errors': len(issues),
            'categories': dict(sorted(counts.items()))
        },
        'issues': issues,
        'generated_at': datetime.now(timezone.utc).isoformat()
    }

    # Human-readable stdout
    cat_parts = [f"{k}={v}" for k, v in sorted(counts.items())]
    print(f"Validation complete: {len(issues)} error(s) found. Categories: {', '.join(cat_parts) if cat_parts else 'none'}")
    for i in issues:
        loc = i['puzzle_id'] or '(no puzzle)'
        if i['scene_id']:
            loc += f" / scene {i['scene_id']}"
        print(f"- [{i['category']}] {loc}: {i['message']}")

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return 1 if issues else 0


if __name__ == '__main__':
    sys.exit(main())
