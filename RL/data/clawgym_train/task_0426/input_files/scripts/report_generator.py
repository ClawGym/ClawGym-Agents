# Simple tour report generator (baseline)
# NOTE: This baseline only computes minimal totals.
# You will need to extend it to read thresholds from config/report.json
# and generate the required outputs per the task instructions.

import csv
import json
import os
from collections import defaultdict, Counter
from datetime import datetime

CONFIG_PATH = os.path.join('config', 'report.json')
CSV_PATH = os.path.join('input', 'tour_feedback.csv')
REPORT_MD_PATH = os.path.join('output', 'docs', 'tour_report.md')
ROUTE_STATS_CSV_PATH = os.path.join('output', 'route_stats.csv')

# Fallback defaults (should be overridden by config)
DEFAULT_CONFIG = {
    'report_title': 'Tour Summary',
    'high_rating_threshold': 4.0,
    'large_group_size': 25,
    'highlight_routes': []
}

STOPWORDS = set(["the","and","a","an","to","of","for","with","but","very","more","great","good","at","on","in","it","is","was","were","be","being","been","this","that","those","these","as","about"])  # extend if needed


def load_config(path=CONFIG_PATH):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return DEFAULT_CONFIG.copy()


def read_rows(csv_path=CSV_PATH):
    rows = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                rows.append({
                    'date': r['date'],
                    'route': r['route'],
                    'group_size': int(r['group_size']),
                    'rating': float(r['rating']),
                    'comment': (r.get('comment') or '').strip()
                })
            except Exception:
                # Skip malformed rows
                continue
    return rows


def ensure_dirs():
    os.makedirs(os.path.dirname(REPORT_MD_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(ROUTE_STATS_CSV_PATH), exist_ok=True)


def basic_totals(rows):
    total_tours = len(rows)
    total_visitors = sum(r['group_size'] for r in rows) if rows else 0
    avg_rating = round(sum(r['rating'] for r in rows)/total_tours, 2) if rows else 0.0
    avg_group = round(total_visitors/total_tours, 2) if rows else 0.0
    return total_tours, total_visitors, avg_rating, avg_group


def write_minimal_report(cfg, rows):
    ensure_dirs()
    total_tours, total_visitors, avg_rating, avg_group = basic_totals(rows)
    lines = []
    lines.append(cfg.get('report_title', 'Tour Summary'))
    lines.append('')
    lines.append('Overview')
    lines.append(f"- Total tours: {total_tours}")
    lines.append(f"- Total visitors: {total_visitors}")
    lines.append(f"- Average rating: {avg_rating}")
    lines.append(f"- Average group size: {avg_group}")
    lines.append('')
    with open(REPORT_MD_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    cfg = load_config()
    rows = read_rows()
    write_minimal_report(cfg, rows)

if __name__ == '__main__':
    main()
