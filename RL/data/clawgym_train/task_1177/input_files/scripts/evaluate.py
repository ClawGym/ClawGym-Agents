import argparse
import json
import os
import re
from typing import Dict, Any, List

# Simple, deterministic evaluator for a monologue using a rubric config.
# Requires only the Python standard library.

def load_text(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def load_config(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    # Validate required top-level keys (will raise KeyError if missing)
    if 'criteria' not in cfg:
        raise KeyError("Config missing required key: 'criteria'")
    if 'weights' not in cfg:
        # Intentionally strict: the key must be exactly 'weights'
        raise KeyError("Config missing required key: 'weights'")
    crit = cfg['criteria']
    for k in ['emotion_keywords', 'pacing', 'clarity']:
        if k not in crit:
            raise KeyError(f"Config criteria missing required key: '{k}'")
    pac = crit['pacing']
    for k in ['short_sentence_threshold', 'long_sentence_threshold']:
        if k not in pac:
            raise KeyError(f"Config pacing missing required key: '{k}'")
    w = cfg['weights']
    # Ensure weights exist for each criterion
    for k in ['emotion', 'pacing', 'clarity']:
        if k not in w:
            raise KeyError(f"Config weights missing required key: '{k}'")
    # Weights sanity check
    total_w = w['emotion'] + w['pacing'] + w['clarity']
    if abs(total_w - 1.0) > 1e-6:
        raise ValueError(f"Weights must sum to 1.0, got {total_w}")
    return cfg

_word_re = re.compile(r"\b\w+\b", re.UNICODE)
_sent_re = re.compile(r"[.!?]+")

def tokenize_words(text: str) -> List[str]:
    return [w.lower() for w in _word_re.findall(text)]

def split_sentences(text: str) -> List[str]:
    # Split on punctuation, filter empty
    parts = _sent_re.split(text)
    return [s.strip() for s in parts if s.strip()]

def score_emotion(words: List[str], emotion_keywords: List[str]) -> Dict[str, Any]:
    ek = set([w.lower() for w in emotion_keywords])
    count = sum(1 for w in words if w in ek)
    # Scale: each match contributes up to 15 points, capped at 100
    score = min(100, count * 15)
    comment = (
        f"Found {count} emotion keyword(s) ({', '.join(sorted(set([w for w in words if w in ek])))}). "
        "A balanced emotional palette helps authenticity."
    )
    return {"score": int(score), "count": count, "comment": comment}

def score_pacing(sentences: List[str], short_thr: int, long_thr: int) -> Dict[str, Any]:
    lengths = [len(tokenize_words(s)) for s in sentences]
    short_count = sum(1 for n in lengths if n > 0 and n < short_thr)
    long_count = sum(1 for n in lengths if n >= long_thr)
    if short_count > 0 and long_count > 0:
        score = 100
    elif (short_count > 0) ^ (long_count > 0):
        score = 60
    else:
        score = 30
    comment = (
        f"Sentence lengths: {lengths}. Short(<{short_thr})={short_count}, Long(>={long_thr})={long_count}. "
        "Varied pacing improves dynamics."
    )
    return {"score": int(score), "short_count": short_count, "long_count": long_count, "lengths": lengths, "comment": comment}

def score_clarity(words: List[str], filler_words: List[str]) -> Dict[str, Any]:
    fw = set([w.lower() for w in filler_words])
    total = max(1, len(words))
    filler_count = sum(1 for w in words if w in fw)
    # Penalty per filler proportional to frequency; subtract up to 100
    penalty = int((filler_count / total) * 400)
    score = max(0, 100 - penalty)
    comment = (
        f"Filler words counted: {filler_count} ({', '.join(sorted(fw))}). "
        "Fewer fillers generally enhance clarity."
    )
    return {"score": int(score), "filler_count": filler_count, "comment": comment}

def evaluate(text: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    words = tokenize_words(text)
    sentences = split_sentences(text)
    emotion_res = score_emotion(words, cfg['criteria']['emotion_keywords'])
    pacing_cfg = cfg['criteria']['pacing']
    pacing_res = score_pacing(sentences, pacing_cfg['short_sentence_threshold'], pacing_cfg['long_sentence_threshold'])
    clarity_res = score_clarity(words, cfg['criteria']['clarity']['filler_words'])

    weights = cfg['weights']
    overall = (
        weights['emotion'] * emotion_res['score'] +
        weights['pacing'] * pacing_res['score'] +
        weights['clarity'] * clarity_res['score']
    )

    criteria_list = [
        {
            "name": "emotion",
            "score": emotion_res['score'],
            "evidence": {"emotion_keywords_matched": emotion_res['count']},
            "comments": emotion_res['comment']
        },
        {
            "name": "pacing",
            "score": pacing_res['score'],
            "evidence": {"short_sentences": pacing_res['short_count'], "long_sentences": pacing_res['long_count'], "lengths": pacing_res['lengths']},
            "comments": pacing_res['comment']
        },
        {
            "name": "clarity",
            "score": clarity_res['score'],
            "evidence": {"filler_count": clarity_res['filler_count']},
            "comments": clarity_res['comment']
        }
    ]

    summary = {
        "overall_score": int(round(overall)),
        "criteria": criteria_list,
        "counts": {
            "words": len(words),
            "sentences": len(sentences)
        }
    }
    return summary

def write_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def write_report_md(path: str, result: Dict[str, Any]) -> None:
    criteria = result.get('criteria', [])
    strengths = [c for c in criteria if c['score'] >= 70]
    improvements = [c for c in criteria if c['score'] < 70]
    lines = []
    lines.append(f"Overall Score: {result.get('overall_score', 0)}/100\n")
    lines.append("Strengths:\n")
    if strengths:
        for c in strengths:
            lines.append(f"- {c['name'].capitalize()}: {c['score']} — {c['comments']}")
    else:
        lines.append("- (none detected)")
    lines.append("\nAreas to Improve:\n")
    if improvements:
        for c in improvements:
            lines.append(f"- {c['name'].capitalize()}: {c['score']} — {c['comments']}")
    else:
        lines.append("- (none detected)")
    with open(path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines) + "\n")

def main():
    parser = argparse.ArgumentParser(description="Evaluate a monologue against a rubric.")
    parser.add_argument('--input', required=True, help='Path to input monologue text file')
    parser.add_argument('--config', required=True, help='Path to rubric JSON config')
    parser.add_argument('--out_dir', required=True, help='Output directory')
    args = parser.parse_args()

    text = load_text(args.input)
    cfg = load_config(args.config)

    os.makedirs(args.out_dir, exist_ok=True)
    result = evaluate(text, cfg)

    out_json = os.path.join(args.out_dir, 'critique.json')
    out_md = os.path.join(args.out_dir, 'report.md')
    write_json(out_json, result)
    write_report_md(out_md, result)
    print(f"Wrote {out_json} and {out_md}")

if __name__ == '__main__':
    main()
