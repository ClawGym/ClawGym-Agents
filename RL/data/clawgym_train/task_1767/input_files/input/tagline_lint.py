import argparse
import json
import re
import sys
from pathlib import Path

CODES = {
    'LENGTH': 'LENGTH',
    'BANNED_PHRASE': 'BANNED_PHRASE',
    'MISSING_CITY': 'MISSING_CITY',
    'ERROR': 'ERROR'
}

def word_count(s: str) -> int:
    # Count word-like tokens; treat contractions as words
    return len(re.findall(r"\b[\w']+\b", s))

def lint_lines(lines, notes, mode):
    warnings = []
    if mode not in {'taglines', 'logline'}:
        print(f"ERROR invalid mode: {mode}")
        return None

    city = (notes.get('city_mention') or '').strip()
    wl = notes.get('word_limits') or {}
    max_words = wl.get('tagline_max_words') if mode == 'taglines' else wl.get('logline_max_words')
    banned = [b.lower() for b in (notes.get('banned_words') or [])]

    for idx, raw in enumerate(lines, start=1):
        text = raw.strip()
        if not text:
            continue
        lc = text.lower()
        # Length check
        wc = word_count(text)
        if isinstance(max_words, int) and wc > max_words:
            warnings.append((idx, CODES['LENGTH'], f"{wc}>{max_words}"))
        # City mention check
        if city and city.lower() not in lc:
            warnings.append((idx, CODES['MISSING_CITY'], city))
        # Banned phrase checks
        for phrase in banned:
            if phrase and phrase in lc:
                warnings.append((idx, CODES['BANNED_PHRASE'], phrase))
    return warnings

def main():
    ap = argparse.ArgumentParser(description='Tagline/logline linter based on collector notes')
    ap.add_argument('--notes', required=True, help='Path to collector_notes.json')
    ap.add_argument('--mode', required=True, choices=['taglines', 'logline'], help='Lint taglines or a logline file')
    ap.add_argument('--input', required=True, help='Path to text file to lint')
    args = ap.parse_args()

    try:
        notes_path = Path(args.notes)
        input_path = Path(args.input)
        if not notes_path.exists():
            print(f"ERROR FileNotFound: notes '{notes_path}'")
            sys.exit(2)
        if not input_path.exists():
            print(f"ERROR FileNotFound: input '{input_path}'")
            sys.exit(2)
        with notes_path.open('r', encoding='utf-8') as f:
            notes = json.load(f)
        with input_path.open('r', encoding='utf-8') as f:
            lines = [ln.rstrip('\n') for ln in f.readlines()]

        warnings = lint_lines(lines, notes, args.mode)
        if warnings is None:
            sys.exit(2)

        total_lines = sum(1 for ln in lines if ln.strip())
        for (lnum, code, detail) in warnings:
            print(f"WARN line={lnum} code={code} detail={detail}")
        if warnings:
            print(f"SUMMARY total_lines={total_lines} warnings={len(warnings)}")
            sys.exit(1)
        else:
            print(f"OK 0 warnings; all lines comply")
            print(f"SUMMARY total_lines={total_lines} warnings=0")
            sys.exit(0)
    except Exception as e:
        print(f"ERROR {e.__class__.__name__}: {e}")
        sys.exit(2)

if __name__ == '__main__':
    main()
