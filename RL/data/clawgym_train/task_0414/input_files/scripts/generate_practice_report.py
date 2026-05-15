import os
import yaml
import pandas as pd

# Generate an aggregated practice report by drill
# NOTE: This script is currently failing; see logs/last_run_error.txt

def main():
    with open('config/report.yml', 'r') as f:
        cfg = yaml.safe_load(f)

    data_path = cfg.get('data_path', 'data/workouts.csv')
    player = cfg.get('player')
    # The YAML has the date column name; default is 'date' if not present
    date_col = cfg.get('date_column', 'date')

    df = pd.read_csv(data_path)

    # BUG: hard-coded 'date' column; should use date_col
    df['date'] = pd.to_datetime(df['date'])

    if player:
        df = df[df['player'] == player]

    grouped = df.groupby('drill', dropna=False).agg(
        total_reps=('reps', 'sum'),
        total_makes=('makes', 'sum'),
        total_misses=('misses', 'sum'),
        total_minutes=('minutes', 'sum')
    ).reset_index()

    grouped['fg_pct'] = grouped['total_makes'] / (grouped['total_makes'] + grouped['total_misses'])

    out_path = 'out/practice_report.csv'

    # BUG: does not ensure output directory exists
    grouped.to_csv(out_path, index=False)
    print(f"Saved to {out_path}")

if __name__ == '__main__':
    main()
