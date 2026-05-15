# ETL canonicalization template for clinic vital-sign exports
# Canonical columns expected downstream:
#   - heart_rate (beats per minute)
#   - systolic_bp (mmHg)
#   - diastolic_bp (mmHg)
#   - temperature_c (Celsius)
#   - timestamp (UTC, ISO8601)
#   - site (clinic/site identifier)
# Use COLUMN_MAP to rename site-specific headers to the above canonical names.

COLUMN_MAP = {
    "HR": "heart_rate",
    "heart_rate_bpm": "heart_rate",
    "SBP": "systolic_bp",
    "systolic": "systolic_bp",
    "DBP": "diastolic_bp",
    "diastolic": "diastolic_bp",
    "TempC": "temperature_c",
    "temperature_c": "temperature_c",
    "timestamp": "timestamp",
    "time": "timestamp",
    "clinic_id": "site",
    "site": "site"
}

# Notes:
# - Timestamps are UTC in the source files (either ending with 'Z' or with '+00:00').
# - Inclusive threshold boundaries should be treated as normal; values strictly outside are abnormal.
# - If a file lacks any canonical column after mapping, record it in the audit.
