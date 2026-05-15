import os
import sys
import re
import json
import csv
from datetime import datetime

BASE_OUTPUT = os.path.join('output')
GUIDE_JSON = os.path.join(BASE_OUTPUT, 'guide.json')
GUIDE_EN = os.path.join(BASE_OUTPUT, 'guide_en.md')
GUIDE_ES = os.path.join(BASE_OUTPUT, 'guide_es.md')

CAMPUS_CSV = os.path.join('input','resources','campus_resources.csv')
COMMUNITY_JSON = os.path.join('input','resources','community_programs.json')
NOTES_MD = os.path.join('input','notes','professor_notes.md')

errors = []

def load_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def read_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()

def parse_glossary_terms(md_text):
    lines = md_text.splitlines()
    terms = []
    i = 0
    while i < len(lines):
        if 'Glossary terms (English):' in lines[i]:
            i += 1
            while i < len(lines):
                line = lines[i].strip('\n')
                if line.strip().startswith('- '):
                    term = line.strip()[2:].strip()
                    if term:
                        terms.append(term)
                    i += 1
                    continue
                # stop on first non-bullet after section
                if line.strip() == '':
                    i += 1
                    break
                else:
                    break
            break
        i += 1
    return terms

def ensure_file_exists(path, label):
    if not os.path.exists(path):
        errors.append(f"Missing {label}: {path}")

# 1) Check existence of output files
ensure_file_exists(GUIDE_JSON, 'guide JSON')
ensure_file_exists(GUIDE_EN, 'English guide markdown')
ensure_file_exists(GUIDE_ES, 'Spanish guide markdown')

if os.path.exists(GUIDE_JSON):
    try:
        g = load_json(GUIDE_JSON)
    except Exception as e:
        errors.append(f"guide.json is not valid JSON: {e}")
        g = None
    if isinstance(g, dict):
        required_keys = {'intro_en','intro_es','campus_resources','community_programs','glossary','last_updated'}
        missing = required_keys - set(g.keys())
        if missing:
            errors.append(f"guide.json missing keys: {sorted(missing)}")
        else:
            # intro checks
            intro_en = g['intro_en']
            intro_es = g['intro_es']
            if not isinstance(intro_en, str) or len(intro_en.strip()) < 100:
                errors.append("intro_en must be a non-empty string (~1–2 paragraphs)")
            if not isinstance(intro_es, str) or len(intro_es.strip()) < 100:
                errors.append("intro_es must be a non-empty string (~1–2 paragraphs)")
            # naive Spanish detection
            es_markers = {' el ', ' la ', ' los ', ' las ', ' de ', ' y ', ' para ', ' estudiantes '}
            es_text = ' ' + intro_es.lower() + ' '
            if sum(1 for m in es_markers if m in es_text) < 2:
                errors.append("intro_es does not appear to be Spanish (basic marker check)")
            # last_updated format
            if not isinstance(g['last_updated'], str) or not re.match(r'^\d{4}-\d{2}-\d{2}$', g['last_updated']):
                errors.append("last_updated must be an ISO date string YYYY-MM-DD")
            # campus resources coverage
            try:
                campus_rows = load_csv(CAMPUS_CSV)
                csv_categories = {r['category'].strip().lower() for r in campus_rows}
            except Exception as e:
                errors.append(f"Failed reading campus CSV: {e}")
                csv_categories = set()
            cr = g.get('campus_resources', [])
            if not isinstance(cr, list) or len(cr) == 0:
                errors.append("campus_resources must be a non-empty list")
            else:
                have_by_cat = {}
                for item in cr:
                    if not isinstance(item, dict):
                        errors.append("Each campus_resources item must be an object")
                        continue
                    for k in ['category','name','description','location','tip']:
                        if k not in item or not str(item[k]).strip():
                            errors.append(f"campus_resources item missing field: {k}")
                    cat = str(item.get('category','')).strip().lower()
                    nm = str(item.get('name','')).strip().lower()
                    if cat:
                        have_by_cat.setdefault(cat, set()).add(nm)
                # verify at least one per CSV category and names align with CSV
                csv_by_cat_names = {}
                for r in campus_rows:
                    c = r['category'].strip().lower()
                    n = r['name'].strip().lower()
                    csv_by_cat_names.setdefault(c, set()).add(n)
                for c in csv_categories:
                    if c not in have_by_cat or len(have_by_cat[c]) == 0:
                        errors.append(f"No campus_resources item for category: {c}")
                    else:
                        # ensure at least one name matches CSV for that category
                        if have_by_cat[c].isdisjoint(csv_by_cat_names.get(c, set())):
                            errors.append(f"campus_resources for category '{c}' do not include any CSV-listed names")
            # community programs coverage
            try:
                community_rows = load_json(COMMUNITY_JSON)
                topics = {}
                for r in community_rows:
                    t = r['topic'].strip()
                    topics.setdefault(t, set()).add(r['program_name'].strip())
            except Exception as e:
                errors.append(f"Failed reading community programs JSON: {e}")
                topics = {}
            cp = g.get('community_programs')
            if not isinstance(cp, dict):
                errors.append("community_programs must be a dictionary keyed by topic")
            else:
                for t, names in topics.items():
                    if t not in cp or not isinstance(cp[t], list) or len(cp[t]) == 0:
                        errors.append(f"Missing or empty community_programs list for topic: {t}")
                    else:
                        listed = {str(x.get('program_name','')).strip() for x in cp[t] if isinstance(x, dict)}
                        if listed.isdisjoint(names):
                            errors.append(f"community_programs for topic '{t}' does not include any known program_name")
            # glossary terms coverage
            notes_text = read_text(NOTES_MD)
            terms = parse_glossary_terms(notes_text)
            gl = g.get('glossary')
            if not isinstance(gl, dict):
                errors.append("glossary must be an object mapping English term to Spanish equivalent")
            else:
                for term in terms:
                    if term not in gl or not str(gl[term]).strip():
                        errors.append(f"glossary missing Spanish equivalent for term: {term}")
    elif g is not None:
        errors.append("guide.json must be a JSON object")

# 2) Check markdowns exist and basic length / language
if os.path.exists(GUIDE_EN):
    en_text = read_text(GUIDE_EN)
    if len(en_text.strip()) < 300:
        errors.append("guide_en.md appears too short (expected ~400–600 words)")
if os.path.exists(GUIDE_ES):
    es_text_md = read_text(GUIDE_ES).lower()
    if len(es_text_md.strip()) < 300:
        errors.append("guide_es.md appears too short (expected length comparable to English)")
    # basic Spanish markers
    markers = [' el ', ' la ', ' los ', ' las ', ' de ', ' y ', ' para ', ' estudiantes ']
    if sum(1 for m in markers if m in ' ' + es_text_md + ' ') < 2:
        errors.append("guide_es.md does not appear to be Spanish (basic marker check)")

if errors:
    print("VALIDATION FAILED:\n" + "\n".join(f"- {e}" for e in errors))
    sys.exit(1)
else:
    print("PASS: All checks succeeded.")
    sys.exit(0)
