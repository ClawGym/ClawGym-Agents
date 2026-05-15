#!/usr/bin/env python3
"""
Compute readability metrics for an English text file and write JSON results.
Outputs (JSON): words, sentences, syllables, flesch_reading_ease, flesch_kincaid_grade.
Usage:
  python tools/readability.py --input <path> --out <output_json>
"""
import argparse
import json
import math
import os
import re
import sys
from typing import List

def split_sentences(text: str) -> List[str]:
    # Naive sentence splitter on ., !, ? while avoiding empty segments
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p.strip()]

def tokenize_words(text: str) -> List[str]:
    # Basic word tokenizer (English alpha words with optional apostrophes)
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)

def count_syllables_in_word(word: str) -> int:
    w = word.lower()
    vowels = "aeiouy"
    if not w:
        return 0
    syllables = 0
    prev_is_vowel = False
    for ch in w:
        is_vowel = ch in vowels
        if is_vowel and not prev_is_vowel:
            syllables += 1
        prev_is_vowel = is_vowel
    # Subtract a syllable for silent 'e' at the end (simple heuristic)
    if w.endswith("e") and syllables > 1:
        syllables -= 1
    # Ensure at least 1 syllable per word
    return max(syllables, 1)

def count_syllables(words: List[str]) -> int:
    return sum(count_syllables_in_word(w) for w in words)

def compute_metrics(text: str) -> dict:
    sentences = split_sentences(text)
    words = tokenize_words(text)
    s_count = len(sentences)
    w_count = len(words)
    sy_count = count_syllables(words)
    # Avoid division by zero
    if s_count == 0 or w_count == 0:
        fre = 0.0
        fk = 0.0
    else:
        fre = 206.835 - 1.015 * (w_count / s_count) - 84.6 * (sy_count / w_count)
        fk = 0.39 * (w_count / s_count) + 11.8 * (sy_count / w_count) - 15.59
    return {
        "words": w_count,
        "sentences": s_count,
        "syllables": sy_count,
        "flesch_reading_ease": round(fre, 3),
        "flesch_kincaid_grade": round(fk, 3),
    }

def main():
    ap = argparse.ArgumentParser(description="Readability metrics (Flesch/FK)")
    ap.add_argument("--input", required=True, help="Path to input text file")
    ap.add_argument("--out", required=True, help="Path to write JSON output")
    args = ap.parse_args()
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            txt = f.read()
    except Exception as e:
        print(f"ERROR: failed to read {args.input}: {e}", file=sys.stderr)
        sys.exit(2)
    metrics = compute_metrics(txt)
    try:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"ERROR: failed to write {args.out}: {e}", file=sys.stderr)
        sys.exit(3)
    # Print a short summary to stdout for logging
    print(f"Analyzed: {args.input}")
    print(f"Sentences: {metrics['sentences']}  Words: {metrics['words']}  Syllables: {metrics['syllables']}")
    print(f"Flesch Reading Ease: {metrics['flesch_reading_ease']}")
    print(f"Flesch-Kincaid Grade: {metrics['flesch_kincaid_grade']}")
    print(f"Wrote JSON to: {args.out}")

if __name__ == "__main__":
    main()
