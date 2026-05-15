import argparse
import json
import re
from pathlib import Path

PATTERN = re.compile(r"^Action:\s*(.+?)\s*-\s*(.+?)(?:;\s*due\s*(\d{4}-\d{2}-\d{2}))?\s*$")

def extract_from_file(path: Path):
    actions = []
    with path.open('r', encoding='utf-8') as f:
        for i, line in enumerate(f, start=1):
            m = PATTERN.match(line.strip())
            if m:
                person = m.group(1).strip()
                task = m.group(2).strip()
                due = (m.group(3) or '').strip()
                actions.append({
                    'source_file': str(path),
                    'line_no': i,
                    'person': person,
                    'task': task,
                    'due_date': due
                })
    return actions


def main():
    parser = argparse.ArgumentParser(description='Extract action items from notes files into JSONL.')
    parser.add_argument('--inputs', nargs='+', required=True, help='One or more input markdown files.')
    parser.add_argument('--out', required=True, help='Output JSONL path.')
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_actions = []
    for p in args.inputs:
        file_actions = extract_from_file(Path(p))
        all_actions.extend(file_actions)

    with out_path.open('w', encoding='utf-8') as out_f:
        for rec in all_actions:
            out_f.write(json.dumps(rec, ensure_ascii=False) + '\n')

if __name__ == '__main__':
    main()
