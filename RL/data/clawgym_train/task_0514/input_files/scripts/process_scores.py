import csv
import os
from pathlib import Path
import re
import sys
import yaml

# Processing script for exam results; designed for simple local, reproducible runs.
# Requires editing to parse pilot schools from HTML and to recursively discover year CSVs under data/.

OUTPUT_DIR = Path('output')
DATA_DIR = Path('data')
CONFIG_PATH = Path('config/analysis.yaml')


def load_config(path: Path):
    with path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def parse_pilot_schools(html_path: Path, out_csv_path: Path):
    """
    Parse meta/pilots.html and return a dict {school_id: school_name}.
    Also write the extracted list to out_csv_path with headers: school_id, school_name.
    NOTE: Implement this. The HTML uses <li data-school-id="S123">School Name</li> under <ul id="pilot-schools">.
    """
    # TODO: Implement HTML parsing and CSV write. Keep to Python standard library.
    raise NotImplementedError('parse_pilot_schools must be implemented to read pilot schools from HTML.')


def discover_csvs(base_dir: Path):
    """
    Discover all CSV files containing results under the data/ directory.
    NOTE: This currently only checks the top level and will miss year subfolders.
    Update it to recursively find CSVs under data/ (e.g., data/2022/*.csv, data/2023/*.csv).
    """
    # TODO: Make this recursive (e.g., using rglob)
    return sorted([p for p in base_dir.glob('*.csv')])


def load_rows(csv_paths):
    rows = []
    for p in csv_paths:
        with p.open('r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    return rows


def categorize_method(method: str, experimental_methods):
    return 'experimental' if method in set(experimental_methods or []) else 'traditional'


def aggregate(rows, pilot_ids, cfg):
    score_field = cfg.get('score_field', 'avg_score')
    min_students = int(cfg.get('min_valid_students', 0))

    groups = {}
    # groups key: (year, group, method_category)
    for r in rows:
        try:
            year = int(r['year'])
            sid = r['school_id']
            students = int(r['students_tested'])
            score = float(r[score_field])
            method_cat = categorize_method(r.get('method', ''), cfg.get('experimental_methods', []))
        except (KeyError, ValueError):
            continue  # skip malformed rows
        if students < min_students:
            continue
        group = 'pilot' if sid in pilot_ids else 'non_pilot'
        key = (year, group, method_cat)
        if key not in groups:
            groups[key] = {
                'schools_count': 0,
                'students_total': 0,
                'score_sum_for_mean': 0.0,
                'weighted_score_sum': 0.0
            }
        groups[key]['schools_count'] += 1
        groups[key]['students_total'] += students
        groups[key]['score_sum_for_mean'] += score
        groups[key]['weighted_score_sum'] += score * students

    # Prepare rows for CSV
    out = []
    for (year, group, method_cat), agg in sorted(groups.items()):
        students_total = agg['students_total']
        average_score_mean = agg['score_sum_for_mean'] / agg['schools_count'] if agg['schools_count'] else 0.0
        average_score_weighted = (agg['weighted_score_sum'] / students_total) if students_total else 0.0
        out.append({
            'year': year,
            'group': group,
            'method_category': method_cat,
            'schools_count': agg['schools_count'],
            'students_total': students_total,
            'average_score_mean': average_score_mean,
            'average_score_weighted': average_score_weighted
        })
    return out


def write_csv(path: Path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def save_effective_config(cfg, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, sort_keys=True)


def main():
    cfg = load_config(CONFIG_PATH)

    # Extract pilot schools and write to output/pilot_schools_extracted.csv
    pilot_html = Path(cfg.get('pilot_html_path', 'meta/pilots.html'))
    pilot_csv_out = OUTPUT_DIR / 'pilot_schools_extracted.csv'
    pilot_map = parse_pilot_schools(pilot_html, pilot_csv_out)
    pilot_ids = set(pilot_map.keys())

    # Discover and load result CSVs
    csv_paths = discover_csvs(DATA_DIR)
    if not csv_paths:
        print('No CSV files discovered under data/. Check discover_csvs implementation.', file=sys.stderr)
        sys.exit(1)
    rows = load_rows(csv_paths)

    # Aggregate
    summary_rows = aggregate(rows, pilot_ids, cfg)

    # Write summary
    summary_path = OUTPUT_DIR / 'summary_by_group.csv'
    write_csv(summary_path, [
        'year', 'group', 'method_category', 'schools_count', 'students_total',
        'average_score_mean', 'average_score_weighted'
    ], summary_rows)

    # Save effective config
    save_effective_config(cfg, OUTPUT_DIR / 'config_effective.yaml')

    print(f'Wrote {summary_path} and {pilot_csv_out}')


if __name__ == '__main__':
    main()
