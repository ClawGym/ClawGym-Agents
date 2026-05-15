#!/usr/bin/env python3
import os, sys, json, re

def parse_html(html):
    # Naive parsing using regex; known to be brittle
    title = re.search(r'<h1>([^<]+)</h1>', html).group(1).strip()
    ep_num = int(re.search(r'Episode (\d+)', title).group(1))
    ep_title = title.split('Episode %d' % ep_num)[1].strip(' :-\u2014') if 'Episode' in title else ''
    air_date_m = re.search(r'Air date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', html)
    air_date = air_date_m.group(1) if air_date_m else None
    quote_m = re.search(r'Standout quote:\s*"([^"]+)"', html)
    quote = quote_m.group(1) if quote_m else None
    elim_section = re.search(r'<section id="eliminations">(.*?)</section>', html, flags=re.S)
    eliminations = []
    if elim_section:
        eliminations = re.findall(r'<li>([^<]+)</li>', elim_section.group(1))
    if eliminations == ['None']:
        eliminations = []
    return {
        "episode_number": ep_num,
        "episode_title": ep_title,
        "air_date": air_date,
        "standout_quote": quote,
        "contestants_eliminated": eliminations,
    }

def main():
    if len(sys.argv) != 3:
        print("Usage: extract_episodes.py <input_dir> <output_json>")
        sys.exit(1)
    input_dir = sys.argv[1]
    output_json = sys.argv[2]
    files = [f for f in os.listdir(input_dir) if f.endswith('.html')]
    episodes = []
    for name in files:
        path = os.path.join(input_dir, name)
        print("Parsing", path)
        with open(path, 'r', encoding='utf-8') as fh:
            html = fh.read()
        data = parse_html(html)
        data['source_file'] = name
        episodes.append(data)
    with open(output_json, 'w', encoding='utf-8') as out:
        json.dump({"episodes": episodes}, out, indent=2)
    print("Wrote", output_json)

if __name__ == '__main__':
    main()
