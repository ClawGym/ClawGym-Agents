import argparse
import os
import re
import json

def mmss(total_seconds):
    m = total_seconds // 60
    s = total_seconds % 60
    return f"{m:02d}:{s:02d}"

def parse_file(path):
    seg_re = re.compile(r"^Segment\s+(\d+)\s*\[(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})\]")
    segments = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            m = seg_re.match(line.strip())
            if m:
                idx = int(m.group(1))
                s_m, s_s, e_m, e_s = map(int, m.groups()[1:])
                start = s_m * 60 + s_s
                end = e_m * 60 + e_s
                if end < start:
                    # skip invalid segment
                    continue
                segments.append({
                    'index': idx,
                    'start': f"{s_m:02d}:{s_s:02d}",
                    'end': f"{e_m:02d}:{e_s:02d}",
                    'duration_sec': end - start
                })
    if not segments:
        return None
    segments.sort(key=lambda x: x['index'])
    total_end_seconds = 0
    if segments:
        last = segments[-1]['end']
        lm, ls = map(int, last.split(':'))
        total_end_seconds = lm * 60 + ls
    return segments, total_end_seconds

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-dir', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    episodes = []
    for name in sorted(os.listdir(args.input_dir)):
        if not name.endswith('.txt'):
            continue
        ep_id = os.path.splitext(name)[0]
        path = os.path.join(args.input_dir, name)
        parsed = parse_file(path)
        if not parsed:
            continue
        segments, total_end_seconds = parsed
        episodes.append({
            'episode_id': ep_id,
            'segment_count': len(segments),
            'segments': segments,
            'total_runtime': mmss(total_end_seconds)
        })
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as out:
        json.dump({'episodes': episodes}, out, indent=2)

if __name__ == '__main__':
    main()
