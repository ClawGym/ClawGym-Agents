#!/usr/bin/env python3
import sys
import json
import re

USAGE = "Usage: python readability_check.py <text_file> <lexicon_json>"

# Simple syllable estimator
VOWELS = set("aeiouy")

def count_syllables(word: str) -> int:
    w = word.lower()
    if not w:
        return 0
    # Remove non-letters for a simpler pass
    w = re.sub(r"[^a-z]", "", w)
    if not w:
        return 0
    # Find groups of vowels
    groups = re.findall(r"[aeiouy]+", w)
    count = len(groups)
    # Trailing 'e' heuristic
    if w.endswith('e') and count > 1:
        count -= 1
    return max(count, 1)

def tokenize_words(text: str):
    return re.findall(r"\b[\w']+\b", text)

def find_line_number(text: str, index: int) -> int:
    return text.count('\n', 0, index) + 1

def split_sentences(text: str):
    # Split on ., !, ? including the punctuation as sentence terminator
    pattern = re.compile(r"[^.!?]+[.!?]")
    sentences = []
    for m in pattern.finditer(text):
        sentences.append((m.group(), m.start()))
    # Handle trailing text without terminal punctuation
    if sentences:
        last_end = sentences[-1][1] + len(sentences[-1][0])
        if last_end < len(text):
            tail = text[last_end:]
            if tail.strip():
                sentences.append((tail, last_end))
    else:
        if text.strip():
            sentences.append((text, 0))
    return sentences

def main():
    if len(sys.argv) != 3:
        print(USAGE, file=sys.stderr)
        sys.exit(1)
    text_path = sys.argv[1]
    lexicon_path = sys.argv[2]

    try:
        with open(text_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        print(f"ERROR: cannot read text file: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(lexicon_path, 'r', encoding='utf-8') as f:
            lexicon = json.load(f)
        avoid = [w.strip() for w in lexicon.get('avoid', []) if w and isinstance(w, str)]
    except Exception as e:
        print(f"ERROR: cannot read lexicon: {e}", file=sys.stderr)
        sys.exit(1)

    words = tokenize_words(text)
    total_words = len(words)
    chars = len(text)

    sentences = split_sentences(text)
    num_sentences = max(len(sentences), 1)

    # Compute syllables
    total_syllables = sum(count_syllables(w) for w in words)

    # Flesch-Kincaid Grade Level
    # 0.39*(words/sentences) + 11.8*(syllables/words) - 15.59
    asl = (total_words / num_sentences) if num_sentences else 0.0
    asw = (total_syllables / total_words) if total_words else 0.0
    fk = 0.39 * asl + 11.8 * asw - 15.59 if total_words and num_sentences else 0.0

    warnings = []

    # Banned words warnings
    for w in avoid:
        if not w:
            continue
        pattern = re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE)
        for m in pattern.finditer(text):
            line = find_line_number(text, m.start())
            warnings.append({
                'type': 'BANNED_WORD_FOUND',
                'detail': w,
                'line': line
            })

    # Long sentence warnings (threshold > 28 words)
    LONG_SENT_THRESHOLD = 28
    for sent, start_idx in sentences:
        sent_words = tokenize_words(sent)
        if len(sent_words) > LONG_SENT_THRESHOLD:
            line = find_line_number(text, start_idx)
            warnings.append({
                'type': 'SENTENCE_TOO_LONG',
                'detail': f"{len(sent_words)} words",
                'line': line
            })

    # Print metrics to STDOUT
    print("READABILITY_METRICS")
    print(f"chars: {chars}")
    print(f"words: {total_words}")
    print(f"sentences: {num_sentences}")
    print(f"avg_sentence_length: {asl:.2f}")
    print(f"flesch_kincaid_grade: {fk:.2f}")

    # Print warnings to STDERR
    for w in warnings:
        if w['type'] == 'BANNED_WORD_FOUND':
            print(f"WARNING: BANNED_WORD_FOUND \"{w['detail']}\" at line {w['line']}", file=sys.stderr)
        elif w['type'] == 'SENTENCE_TOO_LONG':
            print(f"WARNING: SENTENCE_TOO_LONG {w['detail']} at line {w['line']}", file=sys.stderr)

    # Non-zero exit if warnings exist
    sys.exit(2 if warnings else 0)

if __name__ == '__main__':
    main()
