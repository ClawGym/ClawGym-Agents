import argparse
import json
import os
import re
import sys
from datetime import datetime

DEF_EXTS = {'.md'}

SENT_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    if 'keywords' not in cfg or not isinstance(cfg['keywords'], list):
        raise ValueError('config must contain a list field "keywords"')
    case_sensitive = bool(cfg.get('case_sensitive', False))
    keywords = [str(k) for k in cfg['keywords']]
    return keywords, case_sensitive


def extract_from_file(fp, keywords, case_sensitive):
    items = []
    with open(fp, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    qid_counter = 0
    for i, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        # Split sentences within the line
        sentences = SENT_SPLIT_RE.split(line)
        for sent in sentences:
            s_clean = sent.strip()
            if not s_clean:
                continue
            check_text = s_clean if case_sensitive else s_clean.lower()
            matched = []
            for kw in keywords:
                kw_check = kw if case_sensitive else kw.lower()
                if kw_check in check_text:
                    matched.append(kw)
            if matched:
                qid_counter += 1
                items.append({
                    'id': f'Q{qid_counter}',
                    'file': os.path.basename(fp),
                    'line_no': i,
                    'sentence': s_clean,
                    'matched_keywords': sorted(sorted(set(matched)))
                })
    return items


def main():
    ap = argparse.ArgumentParser(description='Extract sentences containing any configured keywords from markdown files.')
    ap.add_argument('--in_dir', required=True, help='Directory with input .md files')
    ap.add_argument('--config', required=True, help='Path to JSON config with keywords')
    ap.add_argument('--out', required=True, help='Output JSON path')
    args = ap.parse_args()

    keywords, case_sensitive = load_config(args.config)

    all_items = []
    for name in sorted(os.listdir(args.in_dir)):
        fp = os.path.join(args.in_dir, name)
        if not os.path.isfile(fp):
            continue
        _, ext = os.path.splitext(name)
        if ext.lower() not in DEF_EXTS:
            continue
        items = extract_from_file(fp, keywords, case_sensitive)
        # Ensure global unique IDs across files by offsetting
        offset = len(all_items)
        for idx, it in enumerate(items, start=1):
            it['id'] = f'Q{offset + idx}'
        all_items.extend(items)

    out_obj = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'keywords': keywords,
        'case_sensitive': case_sensitive,
        'items': all_items
    }

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

    print(f'Wrote {len(all_items)} sentences to {args.out}')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)
