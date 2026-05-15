import sys
import os
import csv


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/check_transcripts.py <catalog_csv>")
        sys.exit(1)

    catalog = sys.argv[1]
    print(f"Loading catalog: {catalog}")

    # Count entries in catalog for user feedback
    try:
        with open(catalog, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            print(f"Catalog entries: {len(rows)}")
    except Exception as e:
        print(f"Failed to read catalog: {e}")

    transcripts_dir = "input/transcript"  # Intentional: directory name is missing 's'
    print(f"Checking transcripts directory: {transcripts_dir}")

    # This will raise FileNotFoundError given the current workspace layout
    files = os.listdir(transcripts_dir)
    print(f"Found {len(files)} transcript files")


if __name__ == "__main__":
    main()
