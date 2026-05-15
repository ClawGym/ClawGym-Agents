from dataclasses import dataclass
from typing import List, Dict

# Event schema reference for the automation output.
# Use this structure when writing out/events/event.json.
# All strings should be JSON-serializable and fields should be present as defined.

@dataclass
class ChangedFile:
    path: str
    # One of: 'modified', 'added', 'removed'
    change_type: str
    # Marker categories map to lists of exact line strings found or changed.
    # Expected keys: 'scenes', 'beats'
    added_markers: Dict[str, List[str]]
    removed_markers: Dict[str, List[str]]

@dataclass
class Event:
    # Must be 'file_change' for this automation
    event_type: str
    # ISO8601 timestamp string, e.g., '2024-03-12T12:00:00Z'
    timestamp: str
    # A list of ChangedFile entries
    changed_files: List[ChangedFile]
    # Summary totals across all scanned files
    # Keys: 'total_scenes', 'total_beats', 'files_scanned'
    summary: Dict[str, int]
