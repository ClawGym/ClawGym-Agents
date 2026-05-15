import csv
import json
from datetime import datetime, timedelta
from collections import defaultdict

# Simple deterministic calendar builder
# Reads config/campaign.json and input/content_ideas.csv, writes out/calendar.csv
# Schedules each idea on date_range_start at the first available time slot for the channel.
# If max per-day per-channel is exceeded, tries the next day within the idea's date range.

CONFIG_PATH = 'config/campaign.json'
INPUT_PATH = 'input/content_ideas.csv'
OUTPUT_PATH = 'out/calendar.csv'

DATE_FMT = '%Y-%m-%d'
TIME_FMT = '%H:%M'

# Initially supported formats; extend if needed
ALLOWED_FORMATS = {"post", "story", "image", "video"}


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_ideas(path):
    ideas = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ideas.append({
                'idea_id': row['idea_id'].strip(),
                'theme': row['theme'].strip(),
                'format': row['format'].strip(),
                'channel': row['channel'].strip(),
                'priority': row['priority'].strip(),
                'date_range_start': row['date_range_start'].strip(),
                'date_range_end': row['date_range_end'].strip(),
                'copy_snippet': row.get('copy_snippet', '').strip()
            })
    return ideas


def within(d, start, end):
    return start <= d <= end


def daterange(start_date, end_date):
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)


def main():
    cfg = load_config(CONFIG_PATH)

    campaign_name = cfg.get('campaign_name', '').strip()
    start_date_str = cfg.get('start_date', '').strip()
    end_date_str = cfg.get('end_date', '').strip()
    timezone = cfg.get('timezone', 'UTC')

    if not start_date_str or not end_date_str:
        raise ValueError('start_date and end_date must be set in config/campaign.json')

    start_date = datetime.strptime(start_date_str, DATE_FMT).date()
    end_date = datetime.strptime(end_date_str, DATE_FMT).date()

    channels = cfg.get('channels', [])
    if not isinstance(channels, list) or not channels:
        raise ValueError('channels must be a non-empty list in config')
    allowed_channels = set(channels)

    time_slots = cfg.get('time_slots', {})
    for ch in allowed_channels:
        if ch not in time_slots or not time_slots[ch]:
            raise ValueError(f'missing time_slots for channel: {ch}')

    max_per_day = int(cfg.get('rules', {}).get('max_posts_per_day_per_channel', 2))

    ideas = load_ideas(INPUT_PATH)

    # Deterministic order by idea_id for stability
    ideas.sort(key=lambda x: int(x['idea_id']))

    # Counters for (date, channel)
    used = defaultdict(int)

    scheduled_rows = []
    for idea in ideas:
        ch = idea['channel']
        fmt = idea['format']

        # Filter unsupported channels or formats
        if ch not in allowed_channels:
            # Skip if channel is not configured
            continue
        if fmt not in ALLOWED_FORMATS:
            # Skip if format not recognized (extend ALLOWED_FORMATS if needed)
            continue

        idea_start = datetime.strptime(idea['date_range_start'], DATE_FMT).date()
        idea_end = datetime.strptime(idea['date_range_end'], DATE_FMT).date()

        # Clamp to campaign window
        window_start = max(start_date, idea_start)
        window_end = min(end_date, idea_end)
        if window_start > window_end:
            # No overlap; skip
            continue

        # Try to place on window_start then subsequent days within window
        placed = False
        for d in daterange(window_start, window_end):
            if used[(d, ch)] < max_per_day:
                # Use the first configured time slot deterministically
                t = time_slots[ch][0]
                # Basic validation of time format
                datetime.strptime(t, TIME_FMT)
                scheduled_rows.append({
                    'idea_id': idea['idea_id'],
                    'channel': ch,
                    'format': fmt,
                    'scheduled_date': d.strftime(DATE_FMT),
                    'scheduled_time': t,
                    'theme': idea['theme'],
                    'priority': idea['priority']
                })
                used[(d, ch)] += 1
                placed = True
                break
        # If not placed, it is omitted by design

    # Ensure output directory exists
    import os
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    with open(OUTPUT_PATH, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['idea_id', 'channel', 'format', 'scheduled_date', 'scheduled_time', 'theme', 'priority']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in scheduled_rows:
            writer.writerow(row)

    # Optional console summary for local verification
    counts = defaultdict(int)
    for r in scheduled_rows:
        counts[r['channel']] += 1
    print(f"Campaign: {campaign_name} ({start_date_str} to {end_date_str} {timezone})")
    for ch in sorted(counts):
        print(f"{ch}: {counts[ch]} posts")

if __name__ == '__main__':
    main()
