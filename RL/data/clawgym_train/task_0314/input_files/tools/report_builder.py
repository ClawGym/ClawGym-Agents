import os
import pandas as pd

# NOTE: This starter script is intentionally rough and may not run as-is.
# Use its errors and output to guide improvements so it produces the required report.

def main():
    # Intentional path/column mismatches to simulate initial failures
    src = "data/calls.csv"  # should reference the real input path
    # Intentionally uses 'timestamp' and 'type' which do not exist in the sample data
    df = pd.read_csv(src, parse_dates=['timestamp'])

    # Compute an incident flag from a non-existent 'type' column
    df['is_incident'] = (df['type'] == 'incident')

    # Group by a non-existent 'family' column
    summary = df.groupby('family').agg(
        total_calls=('family', 'count'),
        welfare_checks=('type', lambda s: (s == 'welfare_check').sum()),
        incidents=('is_incident', 'sum'),
        last_contact_date=('timestamp', 'max')
    ).reset_index()

    # Placeholder logic for recommended_action
    summary['urgent_flag'] = summary['incidents'] > 0
    summary['recommended_action'] = 'TBD'

    out_dir = "report"  # may not match the required output directory
    # This will raise if the directory already exists
    os.makedirs(out_dir)
    out_path = os.path.join(out_dir, "family_summary.csv")
    summary.to_csv(out_path, index=False)
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
