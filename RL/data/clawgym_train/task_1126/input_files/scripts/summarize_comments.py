import os
import sys
import json
import csv
from collections import defaultdict

# Summarize public comments by configurable groups.
# Expected config keys (intent): input_csv, out_dir, group_by, text_column


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_rows(csv_path):
    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader]
    return rows


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def write_csv(path, rows, fieldnames):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def main():
    cfg_path = os.path.join('config', 'config.json')
    print(f"Loading config from {cfg_path}...")
    cfg = load_config(cfg_path)

    # Intentionally strict key access to expose misaligned config keys if present
    input_csv = cfg['input_csv']  # KeyError if config uses a different key
    out_dir = cfg['out_dir']      # KeyError if config uses a different key
    group_by = cfg.get('group_by', [])
    text_col = cfg.get('text_column', 'text')

    print(f"Reading comments from {input_csv}...")
    rows = read_rows(input_csv)
    print(f"Loaded {len(rows)} rows.")

    if not rows:
        print("No data to process.")
        return 0

    if text_col not in rows[0]:
        print(f"ERROR: text column '{text_col}' not in CSV header.")
        return 2

    # Compute word counts
    for r in rows:
        txt = (r.get(text_col) or '').strip()
        r['_word_count'] = len([w for w in txt.split() if w])

    ensure_dir(out_dir)

    # Grouped summary: n_comments and avg_word_count by group_by
    if group_by:
        print(f"Grouping by {group_by}...")
        agg = defaultdict(lambda: {'n': 0, 'sum_words': 0})
        for r in rows:
            key = tuple(r[g] for g in group_by)
            agg[key]['n'] += 1
            agg[key]['sum_words'] += r['_word_count']
        summary_rows = []
        for key, stats in sorted(agg.items()):
            rec = {group_by[i]: key[i] for i in range(len(group_by))}
            rec['n_comments'] = stats['n']
            avg = stats['sum_words'] / stats['n'] if stats['n'] else 0.0
            rec['avg_word_count'] = round(avg, 2)
            summary_rows.append(rec)
        summary_fields = group_by + ['n_comments', 'avg_word_count']
        summary_path = os.path.join(out_dir, 'summary.csv')
        write_csv(summary_path, summary_rows, summary_fields)
        print(f"Wrote {summary_path} with {len(summary_rows)} rows.")

    # stance_totals.csv
    stance_counts = defaultdict(int)
    for r in rows:
        stance_counts[r.get('stance', '')] += 1
    stance_rows = []
    for stance in sorted(stance_counts.keys()):
        stance_rows.append({'stance': stance, 'count': stance_counts[stance]})
    stance_path = os.path.join(out_dir, 'stance_totals.csv')
    write_csv(stance_path, stance_rows, ['stance', 'count'])
    print(f"Wrote {stance_path}.")

    # district_totals.csv: counts by district and oppose_share
    per_district = defaultdict(lambda: {'support': 0, 'oppose': 0, 'neutral': 0})
    for r in rows:
        d = r.get('district', '')
        s = r.get('stance', '')
        if s in per_district[d]:
            per_district[d][s] += 1
        else:
            # Unexpected stance value treated as neutral bucket
            per_district[d]['neutral'] += 1
    district_rows = []
    for d in sorted(per_district.keys()):
        sup = per_district[d]['support']
        opp = per_district[d]['oppose']
        neu = per_district[d]['neutral']
        total = sup + opp + neu
        oppose_share = round((opp / total), 3) if total else 0.0
        district_rows.append({
            'district': d,
            'support': sup,
            'oppose': opp,
            'neutral': neu,
            'total': total,
            'oppose_share': oppose_share
        })
    district_path = os.path.join(out_dir, 'district_totals.csv')
    write_csv(district_path, district_rows, ['district', 'support', 'oppose', 'neutral', 'total', 'oppose_share'])
    print(f"Wrote {district_path}.")

    print("Done.")
    return 0


if __name__ == '__main__':
    try:
        code = main()
        sys.exit(code)
    except Exception as e:
        # Surface stack trace and exit nonzero so the user can capture and inspect errors
        import traceback
        traceback.print_exc()
        sys.exit(1)
