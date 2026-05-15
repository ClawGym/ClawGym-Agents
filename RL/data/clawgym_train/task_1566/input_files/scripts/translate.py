import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import yaml
import difflib

# Stub translator: currently copies source content unchanged.
# You must extend this to apply glossary-based translation, preserve placeholders and terms, and compute metrics.

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / 'config' / 'localization.yml'


def read_text(path: Path) -> str:
    with path.open('r', encoding='utf-8') as f:
        return f.read()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        f.write(text)


def md5_of_text(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def unified_diff(src_text: str, dst_text: str, src_label: str, dst_label: str) -> str:
    src_lines = src_text.splitlines(keepends=True)
    dst_lines = dst_text.splitlines(keepends=True)
    diff = difflib.unified_diff(src_lines, dst_lines, fromfile=src_label, tofile=dst_label)
    return ''.join(diff)


def load_config():
    if not CONFIG_PATH.exists():
        print(f"Config not found at {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    with CONFIG_PATH.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def main():
    cfg = load_config()
    output_dir = ROOT / cfg.get('output_dir', 'output')
    locales = cfg.get('locales', [])
    source_files = [ROOT / p for p in cfg.get('source_files', [])]

    report = {"locales": {}}

    for src in source_files:
        src_text = read_text(src)
        for loc in locales:
            # For now, just copy the source text. You must replace this with real localization per instructions.
            localized = src_text
            rel_out = Path(loc) / src.name
            out_path = output_dir / rel_out
            write_text(out_path, localized)

            # Compute simple metrics (zeros as placeholders for now)
            lines_total = src_text.count('\n') + (0 if src_text.endswith('\n') else 1)
            lines_changed = 0
            glossary_matches = 0
            preserved_placeholders = 0
            preserved_terms = 0
            md5 = md5_of_text(localized)

            # Diff
            qa_dir = output_dir / 'qa'
            qa_dir.mkdir(parents=True, exist_ok=True)
            diff_text = unified_diff(src_text, localized, str(src), f"{loc}/{src.name}")
            diff_path = qa_dir / f"diff-{loc}.txt"
            write_text(diff_path, diff_text)

            # Append report
            report['locales'][loc] = {
                'source': str(src.relative_to(ROOT)),
                'output': str(out_path.relative_to(ROOT)),
                'lines_total': lines_total,
                'lines_changed': lines_changed,
                'glossary_matches': glossary_matches,
                'preserved_placeholders': preserved_placeholders,
                'preserved_terms': preserved_terms,
                'md5': md5
            }

    # Write report
    report_path = output_dir / 'qa' / 'report.json'
    write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2))

    # Print generated paths
    print(str(report_path.resolve()))
    for loc in locales:
        out_file = output_dir / loc / source_files[0].name
        diff_file = output_dir / 'qa' / f'diff-{loc}.txt'
        print(str(out_file.resolve()))
        print(str(diff_file.resolve()))


if __name__ == '__main__':
    main()
