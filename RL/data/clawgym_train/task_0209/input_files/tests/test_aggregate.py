from pathlib import Path
import pandas as pd
from pandas.testing import assert_frame_equal

# Import the function under test
from scripts.aggregate_partners import build_summary


def test_summary_matches_expected():
    output_csv = "outputs/summary.csv"
    Path("outputs").mkdir(exist_ok=True)

    # Run the aggregation
    build_summary("input/engagements.csv", output_csv)

    # Load results and expected
    got = pd.read_csv(output_csv)
    exp = pd.read_csv("tests/expected_summary.csv")

    # Normalize dtypes for comparison
    got["total_hours"] = got["total_hours"].astype(float)
    exp["total_hours"] = exp["total_hours"].astype(float)
    got["mentors_count"] = got["mentors_count"].astype(int)
    exp["mentors_count"] = exp["mentors_count"].astype(int)

    # Sort by key for deterministic comparison
    got_sorted = got.sort_values(["un_agency"]).reset_index(drop=True)
    exp_sorted = exp.sort_values(["un_agency"]).reset_index(drop=True)

    assert_frame_equal(got_sorted, exp_sorted)
