"""
generate_index.py

This script will eventually read a JSON file of review summaries and render a Markdown index.

Current assumptions:
- Source JSON path is defined by SOURCE_JSON.
- Reviews are sorted by title ascending.

TODO: Update the path and sorting when the data format changes.
"""

SOURCE_JSON = "data/reviews.json"
DEFAULT_OUTPUT = "site/generated_index.md"
SORT_KEYS = ["title"]  # ascending by title

def load_reviews(path):
    """Placeholder loader. Left intentionally unimplemented for now."""
    raise NotImplementedError("This is a placeholder.")

if __name__ == "__main__":
    print(f"Would read from {SOURCE_JSON} and write to {DEFAULT_OUTPUT}.")
    print(f"Sort keys: {SORT_KEYS}")
