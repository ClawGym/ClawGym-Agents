#!/usr/bin/env python3
import sys
import json
import csv
import os
from collections import defaultdict

"""
Summarize daily show segments into a digest.
Usage: python scripts/summarize.py <transcripts_jsonl> <lineup_csv> <out_json>
Expected output JSON shape:
{
  "daily": [
    {"date": "YYYY-MM-DD", "shows": [
      {"show_id": str, "title": str, "total_segments": int, "total_duration_sec": int, "top_highlights": [str, ...]}
    ]}
  ]
}
"""

def load_transcripts(path: str):
    # BUG: This incorrectly assumes the transcripts file is a JSON array.
    # Our data is newline-delimited JSON (jsonl), so this will fail and return an empty list.
    with open(path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)  # Will raise JSONDecodeError for jsonl files
            if not isinstance(data, list):
                return []
            return data
        except json.JSONDecodeError:
            print(f"Warning: Failed to parse transcripts as JSON array: {path}")
            return []  # Incorrect fallback; results in empty output


def load_lineup(path: str):
    lineup = {}
    with open(path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row.get('show_id', '').strip()
            if not sid:
                continue
            lineup[sid] = {
                'title': row.get('title', '').strip(),
                'editor_email': row.get('editor_email', '').strip()
            }
    return lineup


def build_digest(transcripts, lineup):
    by_date = defaultdict(list)
    for seg in transcripts:
        d = seg.get('date')
        if not d:
            continue
        by_date[d].append(seg)

    digest = []
    for date in sorted(by_date.keys()):
        shows_map = defaultdict(list)
        for seg in by_date[date]:
            sid = seg.get('show_id')
            if not sid:
                continue
            shows_map[sid].append(seg)

        shows_list = []
        for show_id in sorted(shows_map.keys()):
            segs = shows_map[show_id]
            total_segments = len(segs)
            total_duration = sum(int(s.get('duration_sec', 0)) for s in segs)

            # Collect up to three unique highlights in transcript order
            hl = []
            for s in segs:
                for h in s.get('highlights', []) or []:
                    if h not in hl:
                        hl.append(h)
                    if len(hl) >= 3:
                        break
                if len(hl) >= 3:
                    break

            meta = lineup.get(show_id, {'title': show_id, 'editor_email': ''})
            shows_list.append({
                'show_id': show_id,
                'title': meta.get('title', show_id),
                'total_segments': total_segments,
                'total_duration_sec': total_duration,
                'top_highlights': hl
            })

        digest.append({'date': date, 'shows': shows_list})

    return {'daily': digest}


def main():
    if len(sys.argv) != 4:
        print("Usage: python scripts/summarize.py <transcripts_jsonl> <lineup_csv> <out_json>")
        sys.exit(1)

    transcripts_path = sys.argv[1]
    lineup_path = sys.argv[2]
    out_path = sys.argv[3]

    transcripts = load_transcripts(transcripts_path)
    print(f"Loaded {len(transcripts)} transcripts from {transcripts_path}")

    lineup = load_lineup(lineup_path)
    digest = build_digest(transcripts, lineup)

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(digest, f, indent=2, ensure_ascii=False)
    print(f"Wrote digest to {out_path}")


if __name__ == '__main__':
    main()
