"""
Extractor spec for local HTML snapshots in data/.

Each <article> item has:
- h2.title: text headline
- time[datetime]: ISO date string YYYY-MM-DD
- span.tags: comma-separated tags (e.g., "energy, solar")

When parsing, produce dicts with fields:
- id: stable id (e.g., sha1 of title + date)
- date: YYYY-MM-DD
- month: YYYY-MM
- title: string
- tags: list of lowercase strings with whitespace trimmed
- source_file: relative path of the HTML file
- topic: one of ['solar_energy', 'ai_healthcare', 'stem_education_funding'] or null if no keyword matches per config/topics.yml

The debug JSONL should contain one such dict per article, one JSON object per line.
"""
