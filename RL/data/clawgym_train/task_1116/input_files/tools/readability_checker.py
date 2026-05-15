import sys
import json
import re

USAGE = "Usage: python readability_checker.py INPUT_TEXT_PATH OUTPUT_JSON_PATH"

def split_sentences(text: str):
    text = text.strip()
    if not text:
        return []
    # Naive sentence split on punctuation followed by whitespace
    parts = re.split(r'(?<=[.!?])\s+', text)
    # Ensure no empty tails
    return [p.strip() for p in parts if p.strip()]

def word_count(sentence: str) -> int:
    # Count word-like tokens (letters and apostrophes)
    tokens = re.findall(r"[A-Za-z']+", sentence)
    return len(tokens)

def main():
    if len(sys.argv) != 3:
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    in_path = sys.argv[1]
    out_json = sys.argv[2]

    try:
        with open(in_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        print(f"Error reading {in_path}: {e}", file=sys.stderr)
        sys.exit(1)

    sentences = split_sentences(text)
    results = []
    total_words = 0
    for idx, s in enumerate(sentences, start=1):
        wc = word_count(s)
        total_words += wc
        is_long = wc > 22
        results.append({
            'index': idx,
            'text': s,
            'word_count': wc,
            'is_long': is_long
        })

    total_sentences = len(results)
    avg_len = (total_words / total_sentences) if total_sentences else 0.0

    # Print summary to stdout
    print(f"Total sentences: {total_sentences}")
    print(f"Total words: {total_words}")
    print(f"Average sentence length (words): {avg_len:.2f}")
    for r in results:
        print(f"Sentence {r['index']}: {r['word_count']} words")

    # Issue warnings to stderr for long sentences
    for r in results:
        if r['is_long']:
            print(f"WARNING: Sentence {r['index']} has {r['word_count']} words (>22)", file=sys.stderr)

    payload = {
        'total_sentences': total_sentences,
        'total_words': total_words,
        'avg_sentence_length': avg_len,
        'sentences': results
    }

    try:
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error writing {out_json}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
