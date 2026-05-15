# feature_spec.py
# This lightweight spec documents expected columns and their units for scene-level CSVs.

EXPECTED_COLUMNS = [
    "film_title",
    "scene_id",
    "start_time_s",
    "end_time_s",
    "jump_scare",
    "avg_loudness_db",
    "shot_count",
]

COLUMN_UNITS = {
    "film_title": "string title (e.g., 'Suspiria (1977)')",
    "scene_id": "integer sequence within film",
    "start_time_s": "seconds from film start (float or int)",
    "end_time_s": "seconds from film start (float or int)",
    "jump_scare": "0 or 1 indicator",
    "avg_loudness_db": "approximate integrated loudness per scene (dBFS-like, <=0)",
    "shot_count": "number of camera shots in the scene (int > 0)",
}

NOTES = """
- Durations should be computed as end_time_s - start_time_s.
- Average shot length per scene is (end_time_s - start_time_s) / shot_count.
- Do not assume contiguous scenes; focus on per-scene aggregates.
"""
