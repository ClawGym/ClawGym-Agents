#!/usr/bin/env python3
import argparse
import json
import os
import re
from typing import List, Dict

TAG_LINE_RE = re.compile(r'^#tags:\s*\[(.*?)\]\s*$', re.MULTILINE)
QUOTE_LINE_RE = re.compile(r'^-\s*QUOTE:\s*\"(.*?)\"\s*$', re.MULTILINE)
TITLE_RE = re.compile(r'^Title:\s*(.*)\s*$', re.MULTILINE)
EPISODE_RE = re.compile(r'^Episode:\s*(.*)\s*$', re.MULTILINE)


def parse_tags(text: str) -> List[str]:
    m = TAG_LINE_RE.search(text)
    if not m:
        return []
    raw = m.group(1)
    tags = [t.strip() for t in raw.split(',') if t.strip()]
    return tags


def find_quotes_with_line_numbers(text: str) -> List[Dict]:
    results = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        m = QUOTE_LINE_RE.match(line)
        if m:
            results.append({'quote': m.group(1), 'line_no': idx})
    return results


def parse_title(text: str) -> str:
    m = TITLE_RE.search(text)
    return m.group(1).strip() if m else ''


def parse_episode(text: str) -> str:
    m = EPISODE_RE.search(text)
    return m.group(1).strip() if m else ''


def collect_quotes(notes_dir: str, selected_themes: List[str]) -> List[Dict]:
    out = []
    for root, _dirs, files in os.walk(notes_dir):
        for fn in sorted(f for f in files if f.endswith('.md')):
            path = os.path.join(root, fn)
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
            file_tags = parse_tags(text)
            quotes = find_quotes_with_line_numbers(text)
            title = parse_title(text)
            episode = parse_episode(text)
            relevant = sorted(set(t for t in file_tags if t in selected_themes))
            for q in quotes:
                q_tags = relevant
                if not q_tags:
                    continue
                out.append({
                    'episode': episode,
                    'title': title,
                    'quote': q['quote'],
                    'tags': q_tags,
                    'source_file': os.path.relpath(path),
                    'line_no': q['line_no']
                })
    # Stable sort by episode (numeric if possible), then line_no
    def episode_key(e):
        try:
            return (int(e.get('episode', 0)), e.get('line_no', 0))
        except ValueError:
            return (e.get('episode', ''), e.get('line_no', 0))
    out.sort(key=episode_key)
    return out


def main():
    parser = argparse.ArgumentParser(description='Extract theme-tagged quotes from Night Vale notes.')
    parser.add_argument('--notes', required=True, help='Path to notes directory containing .md files')
    parser.add_argument('--config', required=True, help='Path to JSON config with selected_themes')
    parser.add_argument('--out', required=True, help='Output JSON path')
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as cf:
        cfg = json.load(cf)
    selected = cfg.get('selected_themes', [])
    if not isinstance(selected, list) or not selected:
        raise SystemExit('selected_themes must be a non-empty list in config JSON')

    quotes = collect_quotes(args.notes, selected)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as outf:
        json.dump(quotes, outf, ensure_ascii=False, indent=2)
    print(f'Wrote {len(quotes)} quotes to {args.out}')


if __name__ == '__main__':
    main()
