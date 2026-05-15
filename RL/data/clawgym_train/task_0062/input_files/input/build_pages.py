import os
import json
import glob
from pathlib import Path

# Simple builder: copies article bodies to dist/*.txt
# TODO: prepend disclaimer_text from input/config.json to each output file

def extract_body(md_text: str) -> str:
    if md_text.startswith('---'):
        parts = md_text.split('---', 2)
        if len(parts) >= 3:
            return parts[2].lstrip()
    return md_text

def main():
    with open('input/config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    outdir = Path(cfg.get('build', {}).get('output_dir', 'dist'))
    outdir.mkdir(parents=True, exist_ok=True)

    for md in glob.glob('input/articles/*.md'):
        with open(md, 'r', encoding='utf-8') as fin:
            text = fin.read()
        body = extract_body(text)
        out_path = outdir / (Path(md).stem + '.txt')
        # Currently writes only the body. Modify this script so the configured disclaimer is prepended.
        with open(out_path, 'w', encoding='utf-8') as fout:
            fout.write(body)

if __name__ == '__main__':
    main()
