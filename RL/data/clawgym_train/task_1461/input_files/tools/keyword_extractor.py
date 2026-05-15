#!/usr/bin/env python3
import sys
import os
import re
import json
from collections import Counter

STOPWORDS = set([
    'the','and','for','with','that','this','into','from','about','your','their','will','been','which','were','are','our','you','they','them','then','than','such','also','those','these','have','has','had','but','not','can','could','should','would','over','under','more','most','less','least','very','much','many','some','any','each','every','on','in','at','by','of','to','as','is','be','or','an','a'
])

RE_INDUSTRY = re.compile(r'^\s*industry\s*:\s*(.+)$', re.IGNORECASE)
RE_CONTENT_TYPE = re.compile(r'^\s*content\s*type\s*:\s*(.+)$', re.IGNORECASE)

# map keywords to canonical content_type labels
CT_KEYWORDS = [
    (re.compile(r'\bcase\s*study\b', re.IGNORECASE), 'case_study'),
    (re.compile(r'\bwhite\s*paper\b', re.IGNORECASE), 'white_paper'),
    (re.compile(r'\bblog\b', re.IGNORECASE), 'blog'),
    (re.compile(r'\bwebsite\s*copy\b|\blanding\s*page\b', re.IGNORECASE), 'website_copy'),
]

def infer_content_type(text):
    for pat, label in CT_KEYWORDS:
        if pat.search(text):
            return label
    return 'unknown'

def extract_keywords(text, k=8):
    # words >=5 letters, lowercase, non-stopword
    words = re.findall(r'[a-zA-Z]{5,}', text.lower())
    words = [w for w in words if w not in STOPWORDS]
    counts = Counter(words)
    # sort by count desc, then alphabetical for determinism
    items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    top = [w for w, c in items[:k]]
    return top

def process_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        sys.stderr.write(f"ERROR: could not read {os.path.basename(path)}: {e}\n")
        return None
    industry = 'unknown'
    content_type = 'unknown'
    for line in content.splitlines():
        m = RE_INDUSTRY.match(line)
        if m:
            industry = m.group(1).strip()
        m2 = RE_CONTENT_TYPE.match(line)
        if m2:
            raw = m2.group(1).strip()
            # normalize a few common labels
            low = raw.lower()
            if 'case' in low and 'study' in low:
                content_type = 'case_study'
            elif 'white' in low and 'paper' in low:
                content_type = 'white_paper'
            elif 'blog' in low:
                content_type = 'blog'
            elif 'website' in low and 'copy' in low:
                content_type = 'website_copy'
            else:
                content_type = infer_content_type(content)
    if industry == 'unknown':
        sys.stderr.write(f"WARNING: missing industry in {os.path.basename(path)}\n")
    if content_type == 'unknown':
        # try infer if not set by explicit line
        inferred = infer_content_type(content)
        if inferred == 'unknown':
            sys.stderr.write(f"WARNING: missing or unrecognized content type in {os.path.basename(path)}\n")
        else:
            content_type = inferred
    keywords = extract_keywords(content)
    out = {
        'file': os.path.basename(path),
        'industry': industry,
        'content_type': content_type,
        'keywords': keywords,
    }
    return out

if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.stderr.write('USAGE: python tools/keyword_extractor.py <briefs_dir>\n')
        sys.exit(2)
    briefs_dir = sys.argv[1]
    if not os.path.isdir(briefs_dir):
        sys.stderr.write(f"ERROR: directory not found: {briefs_dir}\n")
        sys.exit(2)
    # process only .txt files, deterministic order
    files = sorted([p for p in os.listdir(briefs_dir) if p.lower().endswith('.txt')])
    for fname in files:
        path = os.path.join(briefs_dir, fname)
        data = process_file(path)
        if data is not None:
            sys.stdout.write(json.dumps(data) + '\n')
