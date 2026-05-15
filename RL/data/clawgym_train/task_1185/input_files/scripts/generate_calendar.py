import json
import csv
import os
from datetime import date, timedelta
from collections import Counter

CONFIG_PATH = 'config/plan.json'
TOPICS_CSV = 'input/topics.csv'
OUTPUT_PATH = 'output/calendar.csv'


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_topics(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: v.strip() for k, v in r.items()})
    if not rows:
        raise ValueError('No topics found in input/topics.csv')
    return rows


def generate_rows(cfg, topics):
    # Expected keys: start_date (YYYY-MM-DD), weeks (int), channels (list[str]), cadence_per_week (dict[str,int])
    start = date.fromisoformat(cfg['start_date'])
    weeks = int(cfg['weeks'])
    channels = cfg['channels']  # Intentional: will KeyError if misnamed/missing
    cadence = cfg['cadence_per_week']

    rows = []
    topic_i = 0
    for w in range(weeks):
        week_start = start + timedelta(days=w * 7)
        for ch in channels:
            per_week = int(cadence.get(ch, 0))
            for p in range(per_week):
                t = topics[topic_i % len(topics)]
                d = week_start + timedelta(days=p)
                message_brief = f"{t['message_seed']} — framed for {ch}"
                rows.append({
                    'date': d.isoformat(),
                    'channel': ch,
                    'theme': t['theme'],
                    'audience_segment': t['audience_segment'],
                    'message_brief': message_brief
                })
                topic_i += 1
    return rows


def write_calendar(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['date', 'channel', 'theme', 'audience_segment', 'message_brief']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def print_summary(rows):
    ch_counts = Counter(r['channel'] for r in rows)
    theme_counts = Counter(r['theme'] for r in rows)
    print('Channel counts:')
    for ch, c in sorted(ch_counts.items()):
        print(f"  {ch}: {c}")
    print('Theme counts:')
    for th, c in sorted(theme_counts.items()):
        print(f"  {th}: {c}")


if __name__ == '__main__':
    cfg = load_config(CONFIG_PATH)
    topics = load_topics(TOPICS_CSV)
    rows = generate_rows(cfg, topics)
    write_calendar(rows, OUTPUT_PATH)
    print_summary(rows)
