import os
import csv
import json
import argparse
from datetime import datetime, timedelta, timezone

CONFIG_PATH = os.path.join('config', 'config.json')


def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser(description='Analyze listening history and write a daily report for a target artist.')
    parser.add_argument('--date', help='YYYY-MM-DD date in UTC to generate report for (defaults to previous day in UTC)')
    args = parser.parse_args()

    # TODO: Implement reading CSV at cfg['csv_path'], filter by cfg['target_artist'] and UTC date, compute stats, and write JSON report under cfg['output_dir'].
    # Expected output fields: date, artist, total_tracks, total_listening_seconds, average_track_duration_seconds (floor), distinct_albums, top_compositions.
    # When --date is not provided, use the previous day in UTC.
    print('analyze_listening is not yet implemented. Loaded target_artist:', cfg.get('target_artist', '(unset)'))


if __name__ == '__main__':
    main()
