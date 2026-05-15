"""
Utilities for a pattern-centric notebook.

Available steps (by function name):
- aggregate_motifs: group rows by motif and compute counts and average complexity
- extract_notes_by_motif: export notes filtered by motif and min complexity
- apply_palette_map: look up a reference color palette for a motif (not currently used)
"""

PALETTE_MAP = {
    "spiral": ["#0F5", "#3A7", "#0A2"],
    "venation": ["#2A9D8F", "#264653", "#97D8C4"],
    "phyllotaxis": ["#F4A261", "#E76F51", "#2A9D8F"],
    "radial": ["#CDB4DB", "#FFC8DD", "#BDE0FE"]
}


def aggregate_motifs(rows):
    """Group by motif and compute count and avg complexity (float). Rows are dicts."""
    pass


def extract_notes_by_motif(rows, motif, min_complexity=0):
    """Filter rows by motif and complexity; return ordered list of note strings."""
    pass


def apply_palette_map(rows, palette_map=PALETTE_MAP):
    """Attach motif palette references from palette_map; return rows with palette info."""
    pass
