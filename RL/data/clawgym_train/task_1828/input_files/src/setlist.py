import csv
from typing import List, Dict
from utils import read_yaml

# NOTE: This function duplicates logic also present in utils.load_songs,
# and expects a 'bpm' field that may not exist in the CSV.
def load_songs(path: str) -> List[Dict]:
    items = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # inconsistent: expects 'bpm' instead of 'tempo'
            try:
                row['bpm'] = int(row.get('bpm') or 0)
            except ValueError:
                row['bpm'] = 0
            # stores seconds even though CSV has minutes
            try:
                row['duration_sec'] = int(float(row.get('duration_min', '0')) * 60)
            except ValueError:
                row['duration_sec'] = 0
            items.append(row)
    return items

# Calculates minutes by summing seconds and dividing, but upstream might not set seconds correctly.
def calculate_set_duration(songs: List[Dict]) -> int:
    total = 0
    for s in songs:
        total += int(s.get('duration_sec', 0))
    return int(total / 60)

def main():
    cfg = read_yaml('config/settings.yaml')
    songs = load_songs('data/songs.csv')
    minutes = calculate_set_duration(songs)
    unit = cfg.get('tempo_unit', 'beatsPerMin')
    print(f"Set duration (min): {minutes} | tempo unit={unit}")

if __name__ == "__main__":
    main()
