import os
import re
import json
import yaml
from typing import List, Dict

DOCS_DIR = os.path.join('input', 'docs')
CONFIG_PATH = os.path.join('config', 'topics.yaml')
OUTPUT_PATH = os.path.join('output', 'excerpts.json')

SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def load_config() -> Dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def read_doc(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def split_sections(text: str) -> List[Dict[str, str]]:
    positions = [(m.start(), m.group(1).strip()) for m in SECTION_RE.finditer(text)]
    sections = []
    if not positions:
        return sections
    positions.append((len(text), None))
    for i in range(len(positions) - 1):
        start, heading = positions[i]
        end, _ = positions[i + 1]
        # Extract section body starting after heading line
        # Find the end of the heading line
        head_line_end = text.find('\n', start)
        if head_line_end == -1:
            head_line_end = start
        body = text[head_line_end:end].strip()
        sections.append({'heading': heading, 'body': body})
    return sections


def match_keywords(body: str, keywords: List[str]) -> List[str]:
    found = []
    lower_body = body.lower()
    for kw in keywords:
        if kw.lower() in lower_body:
            found.append(kw)
    return list(dict.fromkeys(found))  # dedupe while preserving order


def build_records() -> List[Dict]:
    cfg = load_config()
    topics = cfg.get('topics', {})
    records = []
    for fname in os.listdir(DOCS_DIR):
        if not fname.endswith('.md'):
            continue
        path = os.path.join(DOCS_DIR, fname)
        text = read_doc(path)
        sections = split_sections(text)
        for hazard, data in topics.items():
            keywords = data.get('keywords', [])
            for sec in sections:
                matched = match_keywords(sec['body'], keywords)
                if matched:
                    # Take a concise excerpt: first 300 chars of the section body
                    excerpt = sec['body'][:300].strip().replace('\n', ' ')
                    rec = {
                        'hazard': hazard,
                        # TODO: include priority from config in each record (currently omitted)
                        'source_file': fname,
                        'section': sec['heading'],
                        'excerpt': excerpt,
                        'keywords_matched': matched
                    }
                    records.append(rec)
    return records


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    records = build_records()
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(records)} records to {OUTPUT_PATH}")


if __name__ == '__main__':
    main()
