import json
import hashlib
import time
import os
import urllib.request

# Simple RFC downloader (BUGGY)
# Reads input/config.json for settings.
# Intended to download the plain-text RFC and write metadata,
# but currently fetches an HTML info page, truncates content,
# hashes the wrong data, and may fail when output dirs don't exist.

def main():
    with open('input/config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    rfc_number = cfg.get('rfc_number')
    out_text = cfg.get('output_text_path')
    out_meta = cfg.get('output_metadata_path')

    if not rfc_number or not out_text or not out_meta:
        raise SystemExit('Missing required config fields')

    # BUG 1: This is the HTML info page, not the plain-text RFC
    url = f"https://www.rfc-editor.org/info/rfc{rfc_number}"

    # Attempt to fetch (works but returns HTML, not the text RFC)
    resp = urllib.request.urlopen(url, timeout=5)

    # BUG 2: only read a small chunk instead of the full document
    data = resp.read(1024)

    # BUG 3: assume text and decode with ignore, then write text mode
    # This can mangle content and lose bytes
    try:
        os.remove(out_text)
    except FileNotFoundError:
        pass
    with open(out_text, 'w', encoding='utf-8') as f2:
        f2.write(data.decode('utf-8', errors='ignore'))

    # BUG 4: hash the path string instead of the downloaded bytes
    h = hashlib.sha256()
    h.update(out_text.encode('utf-8'))

    meta = {
        "rfc_number": rfc_number,
        "source_url": url,
        "bytes_downloaded": len(data),
        "sha256_hex": h.hexdigest(),
        # BUG 5: first line taken from possibly truncated/HTML content
        "first_line_text": data.decode('utf-8', errors='ignore').splitlines()[0] if data else "",
        "downloaded_at_iso8601": time.strftime("%Y-%m-%dT%H:%M:%S")
    }

    # May fail if directory does not exist
    with open(out_meta, 'w', encoding='utf-8') as f3:
        json.dump(meta, f3, indent=2)

if __name__ == '__main__':
    main()
