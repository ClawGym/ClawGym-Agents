import sys
import re
import json
from pathlib import Path

def extract_articles(md_text):
    lines = md_text.splitlines()
    articles = []
    current = None
    for line in lines:
        m = re.match(r"^##\s+Article\s+(\d+):\s*(.+)$", line.strip())
        if m:
            if current:
                current['text'] = current['text'].strip()
                articles.append(current)
            current = {
                'article_number': int(m.group(1)),
                'article_title': m.group(2).strip(),
                'text': ''
            }
        else:
            if current is not None:
                current['text'] += (line + "\n")
    if current:
        current['text'] = current['text'].strip()
        articles.append(current)
    return articles

def main():
    if len(sys.argv) != 3:
        print("Usage: python tools/extract_clauses.py <input_md> <output_json>")
        sys.exit(1)
    inp = Path(sys.argv[1])
    outp = Path(sys.argv[2])
    if not inp.exists():
        print(f"Input not found: {inp}")
        sys.exit(1)
    md = inp.read_text(encoding='utf-8')
    articles = extract_articles(md)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(articles, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Wrote {len(articles)} articles to {outp}")

if __name__ == "__main__":
    main()
