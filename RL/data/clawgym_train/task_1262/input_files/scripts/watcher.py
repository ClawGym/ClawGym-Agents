import os
import json
import csv
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# Minimal HTML <li> extractor by topic using regex; avoids external deps.
LI_RE = re.compile(r"<li[^>]*data-topic=\"(?P<topic>[^\"]+)\"[^>]*>(?P<text>[^<]+)</li>")

CONFIG_PATH = Path('config/automation.yaml')
RESOURCES_PATH = Path('input/resources.yaml')
STATE_DEFAULT = {"processed": []}


def load_yaml(path):
    if yaml is None:
        raise RuntimeError("PyYAML is required to load YAML files.")
    with open(path, 'r', encoding='utf-8') as fh:
        return yaml.safe_load(fh)


def load_config():
    cfg = load_yaml(CONFIG_PATH)
    # Basic sanity checks; must fail fast if TODOs not replaced.
    if not cfg.get('museum_name') or 'TODO' in str(cfg.get('museum_name')):
        raise ValueError("config.museum_name must be set.")
    if not cfg.get('tone') or 'TODO' in str(cfg.get('tone')):
        raise ValueError("config.tone must be set.")
    return cfg


def ensure_dirs(*paths):
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


def load_state(state_file):
    sf = Path(state_file)
    if not sf.exists():
        return STATE_DEFAULT.copy()
    with open(sf, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def save_state(state_file, state):
    with open(state_file, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, indent=2)


def list_new_csv(trigger_folder, processed):
    folder = Path(trigger_folder)
    folder.mkdir(parents=True, exist_ok=True)
    candidates = []
    for p in folder.glob('bookings_*.csv'):
        if p.name not in processed:
            candidates.append(p)
    return sorted(candidates)


def parse_bookings(csv_path):
    rows = []
    with open(csv_path, 'r', encoding='utf-8') as fh:
        cr = csv.DictReader(fh)
        for r in cr:
            rows.append({
                'tour_id': r['tour_id'].strip(),
                'date': r['date'].strip(),
                'time': r['time'].strip(),
                'group_name': r['group_name'].strip(),
                'group_size': int(r['group_size']),
                'focus': r['focus'].strip(),
                'contact_email': r['contact_email'].strip(),
                'raw_notes': r['notes'].strip()
            })
    return rows


def parse_exhibits_html(html_path):
    text = Path(html_path).read_text(encoding='utf-8')
    mapping = {}
    for m in LI_RE.finditer(text):
        topic = m.group('topic').strip()
        item = m.group('text').strip()
        mapping.setdefault(topic, []).append(item)
    return mapping


def scale_prep_items(base_items, group_size):
    scaled = []
    for item in base_items:
        if ' N ' in f' {item} ':
            # Replace standalone N with group_size
            scaled.append(re.sub(r'\bN\b', str(group_size), item))
        else:
            scaled.append(item)
    return scaled


def rewrite_message(tone, museum_name, booking, highlights, max_sentences):
    # Clean draft if present
    draft = re.sub(r'^\s*Draft msg:\s*', '', booking['raw_notes'], flags=re.IGNORECASE).strip()
    # Core facts
    facts = {
        'date': booking['date'],
        'time': booking['time'],
        'group_name': booking['group_name'],
        'group_size': booking['group_size']
    }
    # Compose a concise message guided by tone; keep within max_sentences
    sentences = []
    sentences.append(f"{museum_name} – thanks for booking {facts['date']} at {facts['time']} for {facts['group_name']} ({facts['group_size']} guests).")
    if highlights:
        hl = ', '.join(highlights[:2])
        sentences.append(f"We'll spotlight: {hl}.")
    # Include a compressed version of draft intent if any
    if draft:
        sentences.append(re.sub(r'\s+', ' ', draft))
    # Accessibility acknowledgement
    if re.search(r'accessibility', booking['raw_notes'], flags=re.IGNORECASE):
        sentences.append("We’ve noted your accessibility needs and will be ready to assist.")
    body = ' '.join(sentences[:max_sentences])
    subject = f"{museum_name} Tour Confirmation – {facts['date']} {facts['time']}"
    return subject, body


def write_notifications(output_root, booking, subject, body):
    out_dir = Path(output_root) / 'notifications' / booking['tour_id']
    ensure_dirs(out_dir)
    (out_dir / 'subject.txt').write_text(subject, encoding='utf-8')
    (out_dir / 'body.txt').write_text(body, encoding='utf-8')


def write_structured(output_root, date_str, records):
    out_dir = Path(output_root) / 'structured'
    ensure_dirs(out_dir)
    out_path = out_dir / f'bookings_{date_str}.json'
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)


def write_meeting_notes(output_root, date_str, bookings_for_date, exhibits_map, resources):
    out_dir = Path(output_root) / 'notes'
    ensure_dirs(out_dir)
    out_path = out_dir / f'meeting_notes_{date_str}.md'
    lines = []
    lines.append(f"Date: {date_str}")
    lines.append("")
    lines.append("Tours:")
    for b in sorted(bookings_for_date, key=lambda x: x['time']):
        highlights = exhibits_map.get(b['focus'], [])[:2]
        hl_text = ', '.join(highlights) if highlights else '—'
        lines.append(f"- {b['tour_id']} – {b['time']} – {b['group_name']} ({b['group_size']}) – {b['focus']} – Highlights: {hl_text}")
    lines.append("")
    lines.append("Action Items:")
    for b in sorted(bookings_for_date, key=lambda x: x['time']):
        base = resources.get('prep', {}).get(b['focus'], [])
        scaled = scale_prep_items(base, b['group_size'])
        lines.append(f"- {b['tour_id']} – {b['focus']}")
        for item in scaled:
            lines.append(f"  - [ ] {item}")
    Path(out_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def process_csv(cfg, csv_path):
    bookings = parse_bookings(csv_path)
    exhibits_map = parse_exhibits_html('input/exhibits.html')
    resources = load_yaml(RESOURCES_PATH)

    # Group by date for outputs
    by_date = {}
    for b in bookings:
        by_date.setdefault(b['date'], []).append(b)

    # Structured output per CSV date (merge all bookings from that CSV date into one file)
    for date_str, items in by_date.items():
        structured_records = []
        for b in items:
            highlights = exhibits_map.get(b['focus'], [])[:2]
            structured_records.append({
                **b,
                'highlights': highlights
            })
            subject, body = rewrite_message(cfg['tone'], cfg['museum_name'], b, highlights, int(cfg.get('message_max_sentences', 3)))
            write_notifications(cfg['output_root'], b, subject, body)
        write_structured(cfg['output_root'], date_str, structured_records)
        write_meeting_notes(cfg['output_root'], date_str, items, exhibits_map, resources)


def main():
    cfg = load_config()
    ensure_dirs(cfg['output_root'], 'state', cfg['trigger_folder'])
    state = load_state(cfg['processed_state_file'])
    new_files = list_new_csv(cfg['trigger_folder'], state.get('processed', []))
    for p in new_files:
        process_csv(cfg, p)
        state.setdefault('processed', []).append(p.name)
        save_state(cfg['processed_state_file'], state)

if __name__ == '__main__':
    main()
