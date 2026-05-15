import os, sys, json, csv, re

INPUT_CSV = os.path.join('input', 'deliverables.csv')
INPUT_HTML = os.path.join('input', 'research_notes.html')
OUT_JSON = os.path.join('output', 'milestones.json')
OUT_PLAN = os.path.join('output', 'project_plan.md')

DATE_RE = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')


def parse_csv(path):
    expected = set()
    with open(path, encoding='utf-8') as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            title = (row.get('deliverable') or '').strip()
            date = (row.get('due_date') or '').strip()
            if title and DATE_RE.fullmatch(date):
                expected.add((title, date))
    return expected


def strip_tags(s):
    return re.sub(r'<[^>]+>', '', s)


def parse_html(path):
    expected = set()
    with open(path, encoding='utf-8') as f:
        html = f.read()
    m = re.search(r'<ul[^>]*id=["\']milestones["\'][^>]*>(.*?)</ul>', html, flags=re.S | re.I)
    if not m:
        return expected
    ul = m.group(1)
    lis = re.findall(r'<li([^>]*)>(.*?)</li>', ul, flags=re.S | re.I)
    for attrs, inner in lis:
        date = None
        mdate = re.search(r'data-date=["\'](\d{4}-\d{2}-\d{2})["\']', attrs)
        if mdate:
            date = mdate.group(1)
        else:
            t = strip_tags(inner)
            mdate2 = DATE_RE.search(t)
            if mdate2:
                date = mdate2.group(1)
        text = strip_tags(inner)
        # Remove parenthetical date if present
        text = re.sub(r'\s*\(\d{4}-\d{2}-\d{2}\)\s*', ' ', text)
        title = re.sub(r'\s+', ' ', text).strip()
        if title and date and DATE_RE.fullmatch(date):
            expected.add((title, date))
    return expected


def load_out_json(path):
    if not os.path.exists(path):
        raise AssertionError(f"Missing output file: {path}")
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise AssertionError('milestones.json must be a list')
    out_set = set()
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise AssertionError(f'Item {i} is not an object')
        for k in ('title', 'date', 'source'):
            if k not in item:
                raise AssertionError(f'Missing key {k} in item {i}')
        title = str(item['title']).strip()
        date = str(item['date']).strip()
        source = str(item['source']).strip().lower()
        if source not in {'csv', 'html'}:
            raise AssertionError(f"Invalid source '{source}' in item {i}")
        if not title or not DATE_RE.fullmatch(date):
            raise AssertionError(f'Invalid title/date in item {i}: {title!r}, {date!r}')
        out_set.add((title, date))
    return out_set


def validate_plan(path, expected_pairs):
    if not os.path.exists(path):
        raise AssertionError(f"Missing output file: {path}")
    with open(path, encoding='utf-8') as f:
        txt = f.read()
    required_headings = ['# Objectives', '# Data Sources', '# Tasks & Timeline', '# Risks & Assumptions']
    for h in required_headings:
        if h not in txt:
            raise AssertionError(f'Missing required heading: {h}')
    for title, date in expected_pairs:
        if title not in txt:
            raise AssertionError(f"Milestone title not found in plan: {title}")
        if date not in txt:
            raise AssertionError(f"Milestone date not found in plan: {date} for {title}")


def main():
    expected_csv = parse_csv(INPUT_CSV)
    expected_html = parse_html(INPUT_HTML)
    expected_union = expected_csv | expected_html
    if not expected_union:
        print('No expected milestones found from inputs.', file=sys.stderr)
        sys.exit(1)
    out_pairs = load_out_json(OUT_JSON)
    if out_pairs != expected_union:
        missing = expected_union - out_pairs
        extra = out_pairs - expected_union
        msg = []
        if missing:
            msg.append('Missing in output: ' + ', '.join([f"{t} [{d}]" for t, d in sorted(missing)]))
        if extra:
            msg.append('Unexpected in output: ' + ', '.join([f"{t} [{d}]" for t, d in sorted(extra)]))
        raise AssertionError('\n'.join(msg))
    validate_plan(OUT_PLAN, expected_union)
    print('All validations passed.')


if __name__ == '__main__':
    try:
        main()
    except AssertionError as e:
        print(f'Validation failed: {e}', file=sys.stderr)
        sys.exit(1)
