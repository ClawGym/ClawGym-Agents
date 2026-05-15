import os
import json
import re
import requests

# NOTE: This script has intentional bugs for debugging.
# Expected behavior (after fixing):
# - Read scraper/config.json for target_domain and save_dir
# - Download main page HTML and robots.txt for the domain
# - Save raw files under workspace/raw/
# - Extract first <h1>, first <p>, and first <a href> from the HTML
# - Save summary JSON under workspace/extracted/
# - Print 'OK example.com' on success

def main():
    cfg_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    domain = cfg.get('target_domain', '').strip()
    if not domain:
        raise RuntimeError('Missing target_domain in config.json')

    # BUG: uses incorrect host format and scheme
    base_url = f"http://www.{domain}"  # should target the main domain, not a subdomain

    # BUG: wrong output directory name
    raw_dir = os.path.join(cfg.get('save_dir', 'workspace'), 'rawl')
    os.makedirs(raw_dir, exist_ok=True)

    html = ''
    try:
        # BUG: expecting JSON from an HTML endpoint
        resp = requests.get(base_url, timeout=2)
        resp.raise_for_status()
        html = resp.json()  # this will raise because it's HTML, not JSON
    except Exception:
        html = ''

    html_path = os.path.join(raw_dir, domain.replace('.', '_') + '.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    # BUG: wrong robots filename path
    robots_url = base_url + '/robot.txt'
    robots_txt = ''
    try:
        r2 = requests.get(robots_url, timeout=2)
        r2.raise_for_status()
        robots_txt = r2.text
    except Exception:
        robots_txt = ''

    robots_path = os.path.join(raw_dir, domain.replace('.', '_') + '_robots.txt')
    with open(robots_path, 'w', encoding='utf-8') as f:
        f.write(robots_txt)

    # BUG: brittle regex (no DOTALL) and may fail if tags span lines
    m_h1 = re.search(r'<h1>(.+)</h1>', html)
    m_p = re.search(r'<p>(.+)</p>', html)
    m_a = re.search(r'href="([^"]+)"', html)

    summary = {
        'domain': domain,
        'h1': m_h1.group(1) if m_h1 else '',
        'p': m_p.group(1) if m_p else '',
        'first_link': m_a.group(1) if m_a else ''
    }

    out_dir = os.path.join(cfg.get('save_dir', 'workspace'), 'extracted')
    # BUG: may not ensure directory exists, and uses ascii encoding
    out_path = os.path.join(out_dir, domain.replace('.', '_') + '_summary.json')
    with open(out_path, 'w', encoding='ascii') as f:
        json.dump(summary, f)

    # BUG: wrong success message
    print('DONE')

if __name__ == '__main__':
    main()
