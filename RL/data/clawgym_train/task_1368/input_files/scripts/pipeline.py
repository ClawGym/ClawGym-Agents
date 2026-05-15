import os
import json
import argparse
from datetime import datetime

# Simple, standard-library-only skeleton. Please extend.

def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def ensure_dirs(paths):
    for p in paths:
        d = p if p.endswith('/') else os.path.dirname(p)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

def read_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def write_text(path, text):
    ensure_dirs([path])
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)

def read_json_list(path):
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(path, data):
    ensure_dirs([path])
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_processed_index(path):
    if not os.path.exists(path):
        return {"processed": [], "last_run": None}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def list_md_files(input_dir):
    if not os.path.exists(input_dir):
        return []
    return [os.path.join(input_dir, fn) for fn in os.listdir(input_dir) if fn.lower().endswith('.md')]

def parse_entry(markdown_text):
    """
    TODO: Implement parsing for:
    - date (YYYY-MM-DD)
    - client (e.g., "A.")
    - emotions: from line starting with "Feelings:" where items look like "sadness (7)"
    - triggers: bullet list under "Triggers:" section
    - coping: bullet list under "Coping:" section
    - poem_lines: bullet list under "Poem lines:" section
    Return a dict with keys: date, client, emotions (list of {name,intensity}), triggers (list), coping (list), poem_lines (list)
    """
    return {}

def top_emotion(emotions):
    if not emotions:
        return None
    # Pick the first with max intensity
    max_val = max(e.get('intensity', 0) for e in emotions)
    for e in emotions:
        if e.get('intensity', 0) == max_val:
            return e
    return None

def generate_reply(entry, template_text, signature):
    """
    TODO: Use a rewritten empathetic template with placeholders {{client}}, {{date}}, {{top_emotion}}.
    Fill the placeholders and append the signature on the last line.
    Return the final message string.
    """
    return template_text + "\n" + signature + "\n"

def merge_entries(existing, new_entries):
    # Deduplicate by source_filename
    seen = {e.get('source_filename') for e in existing}
    merged = list(existing)
    for e in new_entries:
        if e.get('source_filename') not in seen:
            merged.append(e)
    # Sort by date ascending if present
    def _key(e):
        return e.get('date', '')
    merged.sort(key=_key)
    return merged

def update_processed_index(idx_path, added_files):
    idx = load_processed_index(idx_path)
    for f in added_files:
        if f not in idx['processed']:
            idx['processed'].append(f)
    idx['last_run'] = datetime.utcnow().isoformat(timespec='seconds') + 'Z'
    write_json(idx_path, idx)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true', help='Process new files once and exit')
    args = ap.parse_args()

    cfg = load_config('config/automation.json')
    input_dir = cfg['watch']['input_dir']
    idx_path = cfg['watch']['processed_index']
    out_json = cfg['outputs']['structured_json']
    replies_dir = cfg['outputs']['replies_dir']
    notes_path = cfg['outputs']['meeting_notes']
    template_path = cfg['templates']['reply']
    signature = cfg['reply']['signature']

    ensure_dirs([out_json, replies_dir + '/', notes_path, idx_path])

    # Determine new files
    processed_idx = load_processed_index(idx_path)
    all_files = list_md_files(input_dir)
    new_files = [f for f in all_files if os.path.basename(f) not in set(processed_idx.get('processed', []))]

    if not args.once:
        print('This skeleton only supports --once for now. Please implement a poll/watch loop if needed.')

    if args.once:
        new_entries = []
        for path in new_files:
            md = read_text(path)
            entry = parse_entry(md)
            # Ensure required linking back to filename
            entry['source_filename'] = os.path.basename(path)
            new_entries.append(entry)
        # Merge into structured JSON
        existing = read_json_list(out_json)
        merged = merge_entries(existing, new_entries)
        write_json(out_json, merged)
        # Load reply template text
        tmpl = read_text(template_path)
        # Generate replies
        for entry in new_entries:
            fname = os.path.splitext(entry['source_filename'])[0] + '_reply.txt'
            reply_path = os.path.join(replies_dir, fname)
            msg = generate_reply(entry, tmpl, signature)
            write_text(reply_path, msg)
        # TODO: Aggregate meeting notes for entries processed this run into notes_path
        # Implement notes generation with required sections.
        # Update processed index
        update_processed_index(idx_path, [os.path.basename(f) for f in new_files])
        print(f'Processed {len(new_files)} new file(s).')

if __name__ == '__main__':
    main()
