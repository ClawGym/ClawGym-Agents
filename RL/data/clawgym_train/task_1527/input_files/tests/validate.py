import os, sys, json, csv, re

ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(ROOT)

AP = lambda *p: os.path.join(WORKSPACE, *p)

EMAIL_PATH = AP('out', 'email_draft.md')
STATUS_PATH = AP('out', 'status_update.md')
CONTEXT_PATH = AP('input', 'context.json')
EVENTS_PATH = AP('input', 'events.csv')
ARTWORKS_PATH = AP('input', 'artworks.json')
ART_DIR = AP('assets', 'images', 'new_works')


def fail(msg):
    print('VALIDATION FAILED:', msg)
    sys.exit(1)


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_csv(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or '').strip() for k, v in r.items()})
    return rows


def read_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def main():
    # Check inputs exist
    for p in [CONTEXT_PATH, EVENTS_PATH, ARTWORKS_PATH, ART_DIR]:
        if not os.path.exists(p):
            fail(f'Missing required input path: {p}')

    context = load_json(CONTEXT_PATH)
    month_label = context.get('month_label', '').strip()
    if not month_label:
        fail('month_label missing from input/context.json')

    events = load_csv(EVENTS_PATH)
    if not events:
        fail('No events found in input/events.csv')

    exhibition = next((e for e in events if e.get('kind') == 'exhibition'), None)
    workshop = next((e for e in events if e.get('kind') == 'workshop'), None)
    if not exhibition:
        fail('No exhibition found in input/events.csv')
    if not workshop:
        fail('No workshop found in input/events.csv')

    ex_title = exhibition.get('title', '').strip()
    wk_title = workshop.get('title', '').strip()

    artworks = load_json(ARTWORKS_PATH)
    expected_files = {w['filename'] for w in artworks.get('new_works', [])}

    if not os.path.isdir(ART_DIR):
        fail('assets/images/new_works is not a directory')

    present_files = {f for f in os.listdir(ART_DIR) if f.endswith('.txt')}

    if not present_files:
        fail('No files found in assets/images/new_works')

    if present_files != expected_files:
        fail(f'Artwork filenames mismatch. Dir has {sorted(present_files)}, input/artworks.json has {sorted(expected_files)}')

    n_new = len(present_files)

    # Check email draft
    if not os.path.exists(EMAIL_PATH):
        fail('Missing out/email_draft.md')
    email = read_text(EMAIL_PATH)

    # Subject line with month_label
    subj_match = re.search(r'^Subject:\s*(.+)$', email, flags=re.IGNORECASE | re.MULTILINE)
    if not subj_match:
        fail('Email missing Subject line')
    if month_label not in subj_match.group(1):
        fail(f'Subject line must include month label "{month_label}"')

    # Must mention exhibition title
    if ex_title not in email:
        fail(f'Email must mention exhibition title "{ex_title}"')

    # Must mention number of new works and the phrase "new work(s)"
    if 'new work' not in email.lower():
        fail('Email must include the phrase "new work" or "new works"')
    if str(n_new) not in email:
        fail(f'Email must include the number of new works: {n_new}')

    # Must include words painting and purpose
    low = email.lower()
    if 'painting' not in low or 'purpose' not in low:
        fail('Email must include both the words "painting" and "purpose"')

    # At least 3 bullet points (lines starting with "- ")
    bullets = [ln for ln in email.splitlines() if ln.strip().startswith('- ')]
    if len(bullets) < 3:
        fail('Email must include an At-a-glance list with at least 3 bullet points (lines starting with "- ")')

    # Check status update
    if not os.path.exists(STATUS_PATH):
        fail('Missing out/status_update.md')
    status = read_text(STATUS_PATH)

    if 'highlights' not in status.lower():
        fail('Status update must include a "Highlights" section')
    if 'upcoming commitments' not in status.lower():
        fail('Status update must include an "Upcoming commitments" section')

    # Exact bullet: New works: N (case-insensitive on label, exact number)
    pat = re.compile(r'new\s*works\s*:\s*' + re.escape(str(n_new)), flags=re.IGNORECASE)
    if not pat.search(status):
        fail(f'Status update must include a bullet exactly like "New works: {n_new}"')

    if ex_title not in status:
        fail(f'Status update must mention exhibition title "{ex_title}"')
    if wk_title not in status:
        fail(f'Status update must mention workshop title "{wk_title}"')

    print('VALIDATION SUCCESS')

if __name__ == '__main__':
    main()
