import csv
import json
import sys
import os
import re

RED_FLAG_TERMS = [
    "retaliation",
    "corruption",
    "cover-up",
    "bribe",
    "intimidation",
    "vendetta",
    "secret",
    "leak"
]


def analyze_text(text):
    words = re.findall(r"[A-Za-z']+", text)
    word_count = len(words)
    char_count = len(text)
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    avg_word_len = (sum(len(w) for w in words) / word_count) if word_count > 0 else 0.0
    avg_sent_len = (word_count / len(sentences)) if sentences else float(word_count)
    # Simple approximate readability score (0-100): lower is harder
    readability = 100 - (avg_word_len * 10) - (avg_sent_len / 2.0)
    if readability < 0:
        readability = 0.0
    if readability > 100:
        readability = 100.0
    lower = text.lower()
    flags_found = []
    flag_count = 0
    for term in RED_FLAG_TERMS:
        occurrences = lower.count(term)
        if occurrences > 0:
            flag_count += occurrences
            flags_found.append(term)
    return {
        "readability_score": round(readability, 2),
        "red_flag_count": int(flag_count),
        "flagged_terms": sorted(list(set(flags_found))),
        "char_count": int(char_count),
        "word_count": int(word_count)
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/assess_text.py <path_to_quotes_csv>")
        sys.exit(1)
    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"Input not found: {csv_path}")
        sys.exit(1)
    results = {}
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            qid = row.get('id', '').strip()
            text = row.get('quote_text', '')
            metrics = analyze_text(text)
            results[qid] = metrics
    os.makedirs('outputs', exist_ok=True)
    out_path = os.path.join('outputs', 'metrics.json')
    with open(out_path, 'w', encoding='utf-8') as out:
        json.dump(results, out, ensure_ascii=False, indent=2)
    print(f"Wrote metrics to {out_path}")


if __name__ == '__main__':
    main()
