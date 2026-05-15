#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys

# Simple on-page SEO checker for local HTML files.
# Checks per file (mapped by keywords.json):
# - title contains primary keyword and length 30-65
# - meta description contains primary keyword and length 110-160
# - exactly one H1 and it contains primary keyword
# - at least one internal <a href> to a different local page
# - all <img> have non-empty alt
# - canonical link present with href matching the file name

TAG_RE_FLAGS = re.I | re.S

def parse_attrs(s):
    attrs = {}
    for k, v in re.findall(r"(\w+)\s*=\s*['\"]([^'\"]*)['\"]", s, flags=TAG_RE_FLAGS):
        attrs[k.lower()] = v
    return attrs

def extract_title(html):
    m = re.search(r"<title>(.*?)</title>", html, flags=TAG_RE_FLAGS)
    return m.group(1).strip() if m else None

def extract_meta_description(html):
    desc = None
    for m in re.finditer(r"<meta\s+([^>]+)>", html, flags=TAG_RE_FLAGS):
        attrs = parse_attrs(m.group(1))
        if attrs.get('name', '').lower() == 'description':
            desc = attrs.get('content')
            break
    return (desc or '').strip() if desc else None

def extract_h1s(html):
    return [t.strip() for t in re.findall(r"<h1[^>]*>(.*?)</h1>", html, flags=TAG_RE_FLAGS)]

def extract_img_alts(html):
    alts = []
    for m in re.finditer(r"<img\b([^>]*)>", html, flags=TAG_RE_FLAGS):
        attrs = parse_attrs(m.group(1))
        alts.append(attrs.get('alt', ''))
    return alts

def extract_links(html):
    return re.findall(r"<a\s+[^>]*href=['\"]([^'\"]+)['\"]", html, flags=TAG_RE_FLAGS)

def extract_canonical(html):
    for m in re.finditer(r"<link\s+([^>]+)>", html, flags=TAG_RE_FLAGS):
        attrs = parse_attrs(m.group(1))
        rel = attrs.get('rel', '').lower()
        if rel == 'canonical':
            return attrs.get('href')
    return None

def within_len(s, lo, hi):
    if s is None:
        return False
    n = len(s.strip())
    return lo <= n <= hi

def contains_kw(s, kw):
    if s is None:
        return False
    return kw.lower() in s.lower()

def check_file(path, fname, html, kw_map, site_filenames):
    primary_kw = kw_map.get(fname, {}).get('primary_keyword', '').strip()
    res = {
        'file': fname,
        'primary_keyword': primary_kw,
        'checks': {},
        'notes': []
    }

    title = extract_title(html)
    md = extract_meta_description(html)
    h1s = extract_h1s(html)
    alts = extract_img_alts(html)
    links = extract_links(html)
    canonical = extract_canonical(html)

    # Title checks
    c_title_kw = contains_kw(title, primary_kw)
    c_title_len = within_len(title, 30, 65)

    # Meta description checks
    c_md_kw = contains_kw(md, primary_kw)
    c_md_len = within_len(md, 110, 160)

    # H1 checks
    c_single_h1 = (len(h1s) == 1)
    c_h1_kw = contains_kw(h1s[0] if h1s else None, primary_kw)

    # Internal links
    internal_count = 0
    for href in links:
        base = os.path.basename(href.strip())
        if base in site_filenames and base != fname:
            internal_count += 1
    c_internal = internal_count >= 1

    # Image alts
    c_img_alts = all([alt.strip() != '' for alt in alts]) if alts else True

    # Canonical
    c_canonical_present = canonical is not None
    c_canonical_matches = False
    if canonical:
        c_canonical_matches = (os.path.basename(canonical.strip()) == fname)

    res['checks'] = {
        'title_keyword': c_title_kw,
        'title_length': c_title_len,
        'meta_keyword': c_md_kw,
        'meta_length': c_md_len,
        'single_h1': c_single_h1,
        'h1_keyword': c_h1_kw,
        'internal_link': c_internal,
        'img_alt': c_img_alts,
        'canonical_present': c_canonical_present,
        'canonical_matches': c_canonical_matches
    }

    for k, v in res['checks'].items():
        if not v:
            res['notes'].append(f"FAIL: {k}")

    res['file_pass'] = all(res['checks'].values())
    return res

def main():
    ap = argparse.ArgumentParser(description='Local on-page SEO checker')
    ap.add_argument('--site-dir', required=True)
    ap.add_argument('--keywords', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--fail-on-issues', action='store_true')
    args = ap.parse_args()

    with open(args.keywords, 'r', encoding='utf-8') as f:
        kw_map = json.load(f)

    site_dir = args.site_dir
    site_files = [f for f in os.listdir(site_dir) if f.lower().endswith('.html')]
    site_filenames = set(site_files)

    per_file = {}
    any_fail = False

    for fname in sorted(site_files):
        # Only check files that have a mapping in keywords.json
        if fname not in kw_map:
            continue
        path = os.path.join(site_dir, fname)
        with open(path, 'r', encoding='utf-8') as f:
            html = f.read()
        res = check_file(path, fname, html, kw_map, site_filenames)
        per_file[fname] = res
        if not res['file_pass']:
            any_fail = True

    summary = {
        'files_checked': len(per_file),
        'files_passed': sum(1 for v in per_file.values() if v['file_pass']),
        'files_failed': sum(1 for v in per_file.values() if not v['file_pass'])
    }
    report = {
        'files': per_file,
        'summary': summary,
        'overall_pass': (summary['files_failed'] == 0 and summary['files_checked'] > 0)
    }

    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2))
    if args.fail_on_issues and not report['overall_pass']:
        sys.exit(1)
    sys.exit(0)

if __name__ == '__main__':
    main()
