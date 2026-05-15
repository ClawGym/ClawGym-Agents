import os
import json

def read_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    # Expect a 'categories' key; will raise KeyError if missing
    categories = cfg['categories']
    tag_synonyms = cfg.get('tag_synonyms', {})
    return categories, tag_synonyms

def normalize_tag(t, syn):
    t = t.strip().lower()
    return syn.get(t, t)

def parse_notes(path, syn):
    notes = []
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    current = None
    for raw in lines:
        line = raw.strip()
        if line.startswith('## '):
            if current:
                notes.append(current)
            current = {'title': line[3:].strip(), 'tags': [], 'draft_summary': ''}
        elif line.lower().startswith('keywords:') and current:
            val = line.split(':', 1)[1]
            tags = [normalize_tag(t, syn) for t in val.split(',')]
            tags = sorted({t for t in tags if t})
            current['tags'] = tags
        elif line.lower().startswith('draft summary:') and current:
            current['draft_summary'] = line.split(':', 1)[1].strip()
    if current:
        notes.append(current)
    return notes

def main():
    categories, tag_synonyms = read_config('config/tag_rules.json')
    notes = parse_notes('input/notes/beliefs_and_values.md', tag_synonyms)
    os.makedirs('output', exist_ok=True)

    index = []
    for n in notes:
        index.append({
            'title': n['title'],
            'tags': n['tags'],
            'has_draft_summary': bool(n['draft_summary']),
            'config_categories': categories
        })
    with open('output/notes_index.json', 'w', encoding='utf-8') as out:
        json.dump({'notes': index}, out, ensure_ascii=False, indent=2)

    with open('output/rough_summaries.md', 'w', encoding='utf-8') as out:
        out.write('Rough Summaries\n')
        out.write('---------------\n')
        for i, n in enumerate(notes, 1):
            out.write(f"{i}. {n['title']}: ")
            if n['draft_summary']:
                out.write(n['draft_summary'] + "\n")
            else:
                out.write('No draft summary provided.\n')

if __name__ == '__main__':
    main()
