import pandas as pd
from pathlib import Path

def main():
    inp = Path("data/bookings.csv")
    out = Path("output/summary.csv")
    df = pd.read_csv(inp)

    # BUG: This mask finds cancelled/hold rows, but the next line keeps them instead of excluding.
    cancel_mask = df['status'].str.contains('cancel|hold', case=False, na=False)
    df = df[cancel_mask]  # should exclude cancelled/hold, not keep them

    # BUG: No de-duplication. Exact duplicate rows will be double-counted.

    # Date and grouping
    df['event_date'] = pd.to_datetime(df['event_date'], errors='coerce')
    df['year_month'] = df['event_date'].dt.strftime('%Y-%m')

    summary = df.groupby('year_month').agg(
        total_events=('booking_id', 'count'),
        total_revenue=('total_amount', 'sum'),
        avg_guests=('guests', 'mean'),
    ).reset_index().sort_values('year_month')

    out.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out, index=False)

if __name__ == "__main__":
    main()
