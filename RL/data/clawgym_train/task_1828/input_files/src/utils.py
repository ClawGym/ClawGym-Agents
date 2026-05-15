import csv
import yaml
from typing import List, Dict, Any

def read_yaml(path: str) -> Dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}

# NOTE: This is a second CSV loader; it normalizes 'tempo' but not 'bpm'.
def load_songs(path: str) -> List[Dict[str, Any]]:
    """Load songs from CSV, normalizing 'tempo' to int if present."""
    songs = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tempo = row.get('tempo') or row.get('bpm') or ''
            try:
                row['tempo'] = int(float(tempo))
            except ValueError:
                row['tempo'] = ''
            songs.append(row)
    return songs

def average_tempo(songs: List[Dict[str, Any]], unit: str) -> float:
    """Return average tempo, assumes 'tempo' is in beatsPerMin if unit matches."""
    values = [int(s['tempo']) for s in songs if str(s.get('tempo')).isdigit()]
    if not values:
        return 0.0
    if unit == 'beatsPerMin':
        return sum(values) / len(values)
    # fallback passthrough
    return sum(values) / len(values)
