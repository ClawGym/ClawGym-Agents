import os
import json
import glob
import re
import sys

def parse_note(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    title = None
    date = None
    tags = None
    for line in lines[:20]:
        m = re.match(r'\s*Title:\s*(.+)', line)
        if m:
            title = m.group(1).strip()
        m = re.match(r'\s*Date:\s*(\d{4}-\d{2}-\d{2})', line)
        if m:
            date = m.group(1).strip()
        m = re.match(r'\s*Tags:\s*(.+)', line)
        if m:
            tags = [t.strip().lower() for t in m.group(1).split(',') if t.strip()]
    if not (title and date and tags):
        raise ValueError(f"Missing required fields in {path}. Found title={bool(title)}, date={bool(date)}, tags={bool(tags)}")
    return {
        'title': title,
        'date': date,
        'tags': tags,
        'path': path
    }


def main():
    cfg_path = os.path.join('config', 'settings.json')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    # Expected keys in config
    notes_dir = cfg['notes_dir']
    categories = cfg['categories']  # KeyError will occur if misconfigured

    note_paths = sorted(glob.glob(os.path.join(notes_dir, '*.md')))
    notes = []
    for p in note_paths:
        notes.append(parse_note(p))

    # Assign categories to each note by matching tag keywords
    for note in notes:
        cats = []
        for cat, keys in categories.items():
            for key in keys:
                if key.lower() in note['tags']:
                    cats.append(cat)
                    break
        note['categories'] = sorted(set(cats))

    # Aggregate counts and tags
    counts = {}
    all_tags = set()
    for note in notes:
        for t in note['tags']:
            all_tags.add(t)
        for cat in note['categories']:
            counts[cat] = counts.get(cat, 0) + 1

    index = {
        'notes': notes,
        'category_counts': counts,
        'all_tags': sorted(all_tags)
    }

    out_dir = 'out'
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'index.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print(f"Indexed {len(notes)} notes.")
    print("Category counts:")
    for cat in sorted(counts.keys()):
        print(f"- {cat}: {counts[cat]}")
    print(f"Wrote {out_path}")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        raise
