import os
import sys
import json
import csv
import re
from pathlib import Path

REQUIRED_ISSUE_HEADERS = [
    'article_number', 'article_title', 'issue_type', 'statute_ref', 'risk_score', 'summary'
]

def fail(msg):
    print(f"VALIDATION FAILED: {msg}")
    sys.exit(1)

def check_extracted_clauses():
    p = Path('workspace/extracted_clauses.json')
    if not p.exists():
        fail('workspace/extracted_clauses.json not found. Did you run the extractor?')
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        fail(f'Cannot parse extracted_clauses.json: {e}')
    if not isinstance(data, list) or len(data) < 6:
        fail('extracted_clauses.json must be a list with at least 6 articles.')
    # Must contain expected keys
    for i, item in enumerate(data):
        for k in ['article_number', 'article_title', 'text']:
            if k not in item:
                fail(f'Missing key {k} in article index {i}.')
    return data

def check_critique(articles):
    p = Path('workspace/treaty_critique.md')
    if not p.exists():
        fail('workspace/treaty_critique.md not found.')
    txt = p.read_text(encoding='utf-8')
    if 'Executive Summary' not in txt:
        fail('treaty_critique.md must include an "Executive Summary" section.')
    # Ensure at least one article title appears in the critique
    titles = [a['article_title'] for a in articles]
    if not any(t in txt for t in titles):
        fail('treaty_critique.md should reference at least one article title.')


def check_issues():
    p = Path('workspace/issues.csv')
    if not p.exists():
        fail('workspace/issues.csv not found.')
    try:
        with p.open('r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception as e:
        fail(f'Cannot read issues.csv: {e}')
    if not rows:
        fail('issues.csv is empty.')
    header = [h.strip() for h in rows[0]]
    for h in REQUIRED_ISSUE_HEADERS:
        if h not in header:
            fail(f'issues.csv missing required column: {h}')
    # Map header to index
    idx = {h: header.index(h) for h in REQUIRED_ISSUE_HEADERS}
    if len(rows) < 4:  # header + at least 3 issues
        fail('issues.csv must contain at least 3 issues (rows).')
    for r in rows[1:]:
        try:
            rs = float(r[idx['risk_score']])
        except Exception:
            fail('risk_score must be numeric between 0 and 1.')
        if rs < 0 or rs > 1:
            fail('risk_score out of range [0,1].')
        if not r[idx['article_number']].strip() or not r[idx['article_title']].strip():
            fail('Each issue must include article_number and article_title.')
        if not r[idx['statute_ref']].strip():
            fail('Each issue must cite at least one statute_ref.')
        if not r[idx['summary']].strip():
            fail('Each issue must include a summary.')


def check_meeting_notes():
    p = Path('workspace/meeting_notes.md')
    if not p.exists():
        fail('workspace/meeting_notes.md not found.')
    txt = p.read_text(encoding='utf-8')
    if 'Action Items' not in txt:
        fail('meeting_notes.md must include an "Action Items" section.')
    # At least one action item should reference an Article and have an Owner
    if 'Owner:' not in txt:
        fail('Each action item should assign an Owner. Include "Owner:" markers in the notes.')
    if 'Article' not in txt:
        fail('Action items should reference an Article number by name (e.g., "Article 2").')


def main():
    articles = check_extracted_clauses()
    check_critique(articles)
    check_issues()
    check_meeting_notes()
    print('Validation passed. All required outputs are present and structurally sound.')
    sys.exit(0)

if __name__ == '__main__':
    main()
