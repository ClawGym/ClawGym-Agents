import json
import re
from datetime import datetime
from typing import List, Dict

EVENT_RE = re.compile(r'<div\s+class="event"\s+([^>]*)>\s*</div>')
ATTR_RE = re.compile(r'(data-(title|date|city|venue|creators))="([^"]*)"')

SLUG_CLEAN_RE = re.compile(r'[^a-z0-9\s-]')
MULTI_DASH_RE = re.compile(r'-{2,}')


def slugify(title: str) -> str:
    s = title.lower()
    s = SLUG_CLEAN_RE.sub('', s)
    s = re.sub(r'\s+', '-', s.strip())
    s = MULTI_DASH_RE.sub('-', s)
    return s


def parse_events(html_path: str) -> List[Dict]:
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    events = []
    for m in EVENT_RE.finditer(html):
        attrs = dict((k, v) for (k, _, v) in ATTR_RE.findall(m.group(1)))
        title = attrs.get('data-title', '').strip()
        date_str = attrs.get('data-date', '').strip()
        city = attrs.get('data-city', '').strip()
        venue = attrs.get('data-venue', '').strip()
        creators_str = attrs.get('data-creators', '').strip()
        creators = [c.strip() for c in creators_str.split(',') if c.strip()]
        # Validate date format and normalize
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            norm_date = dt.strftime('%Y-%m-%d')
        except ValueError:
            raise ValueError(f'Invalid date format for event "{title}": {date_str}')
        evt = {
            'id': slugify(title),
            'title': title,
            'date': norm_date,
            'city': city,
            'venue': venue,
            'creators': creators,
        }
        events.append(evt)
    # Sort by date ascending
    events.sort(key=lambda e: e['date'])
    return events


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3:
        print('Usage: python src/event_parser.py <input_html> <output_json>')
        sys.exit(1)
    inp, outp = sys.argv[1], sys.argv[2]
    data = parse_events(inp)
    with open(outp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'Wrote {len(data)} events to {outp}')
