"""
Utility for building indexes from poetry datasets.

Expected output schema:
- poets.json: list of objects with these fields (see SCHEMA['poets_json_fields']):
  - author: str
  - poem_count: int
  - appears_in_schedule: bool
  - first_appearance_date: ISO 8601 date string or null
  - sample_titles: list[str] (up to 3)
- poems_by_theme.csv: CSV with columns (see SCHEMA['poems_by_theme_fields']):
  - title, author, year, canonical_theme

Inputs (paths are provided for reference; you may implement your own tooling):
- input/library/poems.csv
- input/web/schedule.html
- config/taxonomy.yaml

Outputs (recommended paths):
- outputs/poets.json
- outputs/poems_by_theme.csv
"""

SCHEMA = {
    "poets_json_fields": [
        "author",
        "poem_count",
        "appears_in_schedule",
        "first_appearance_date",
        "sample_titles"
    ],
    "poems_by_theme_fields": [
        "title",
        "author",
        "year",
        "canonical_theme"
    ]
}

INPUTS = {
    "poems_csv": "input/library/poems.csv",
    "schedule_html": "input/web/schedule.html",
    "taxonomy_yaml": "config/taxonomy.yaml"
}

OUTPUTS = {
    "poets_json": "outputs/poets.json",
    "poems_by_theme_csv": "outputs/poems_by_theme.csv"
}

if __name__ == "__main__":
    print("This module documents expected schemas via SCHEMA. Inspect SCHEMA to align outputs.")
