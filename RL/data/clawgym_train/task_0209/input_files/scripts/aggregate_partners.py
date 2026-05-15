from pathlib import Path
import sys
import pandas as pd


def build_summary(input_csv: str, output_csv: str) -> None:
    """
    Build a summary of mentor engagement by UN agency.
    - Reads input_csv with columns including: partner, un_agency, role, hours_mentored.
    - Filters for mentor rows and aggregates total hours and mentor counts per agency.
    - Writes CSV to output_csv with columns: un_agency,total_hours,mentors_count

    Note: Known issue for you to fix: role filtering is case-sensitive and hours may be summed incorrectly.
    """
    # BUG: reading all as str causes numeric aggregation issues
    df = pd.read_csv(input_csv, dtype=str)

    # BUG: case-sensitive filter misses 'Mentor'
    mentors = df[df["role"] == "mentor"]

    # BUG: summing strings and counting rows (not unique mentors)
    summary = mentors.groupby("un_agency", as_index=False).agg(
        total_hours=("hours_mentored", "sum"),
        mentors_count=("partner", "count"),
    )

    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_csv, index=False)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python scripts/aggregate_partners.py input/engagements.csv outputs/summary.csv"
        )
        sys.exit(1)
    build_summary(sys.argv[1], sys.argv[2])
