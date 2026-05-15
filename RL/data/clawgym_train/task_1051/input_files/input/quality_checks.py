"""
Quality gates and tie-break settings for processing the UCI WDBC dataset.
Use these constants to validate the raw file and to apply deterministic tie-breaking.
"""

# Dataset shape expectations
EXPECTED_RECORDS = 569
EXPECTED_FEATURES = 32  # includes id and diagnosis

# Allowed diagnosis labels
VALID_LABELS = {"M", "B"}

# The exact raw file name to download from the official dataset page
RAW_FILE_NAME = "wdbc.data"

# Tie-breaking order and direction for ranking (apply in this list order)
TIEBREAK_ORDER = [
    "area_worst",
    "concave_points_worst",
    "radius_mean"
]
# Apply descending comparisons for each tiebreak feature
TIEBREAK_DIRECTION = "desc"
