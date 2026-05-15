# quick-and-dirty event collector (needs refactor)
import os, json

def main():
    p = 'input/events.html'
    txt = open(p, 'r', encoding='utf-8').read()
    parts = txt.split('<div class="event"')
    results = []
    for i in range(1, len(parts)):
        block = '<div class="event"' + parts[i]
        try:
            did = block.split('data-id="')[1].split('"')[0]
            ttl = block.split('<h3 class="title">')[1].split('</h3>')[0]
            dt = block.split('<time datetime="')[1].split('"')[0]
            city = block.split('<span class="city">')[1].split('</span>')[0]
            st = block.split('<span class="state">')[1].split('</span>')[0]
            topics_section = block.split('<ul class="topics">')[1].split('</ul>')[0]
            items = []
            for seg in topics_section.split('<li>')[1:]:
                items.append(seg.split('</li>')[0].strip())
            host = block.split('<span class="host">')[1].split('</span>')[0]
            results.append({"id": did, "title": ttl.strip(), "date": dt, "city": city.strip(), "state": st.strip(), "topics": items, "host": host.strip()})
        except Exception as e:
            print('skip block err:', e)
    print('events:', len(results))
    os.makedirs('output', exist_ok=True)
    # not real JSON (Python repr) — to be fixed in refactor
    open('output/raw.json', 'w', encoding='utf-8').write(str(results))
    open('output/raw.txt', 'w', encoding='utf-8').write('\n'.join([x['id'] + ':' + x['title'] for x in results]))

if __name__ == '__main__':
    main()
