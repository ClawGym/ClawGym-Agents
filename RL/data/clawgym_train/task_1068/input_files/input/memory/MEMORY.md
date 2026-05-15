# Long-term Memory

This workspace maintains durable notes for decisions, ongoing projects, search practices, and daily logs. Use memory to keep a coherent record that can be retrieved reliably with hybrid search.

## Principles

- Keep important decisions and checklists in Markdown with clear headers.
- Prefer concise language and precise nouns so keyword overlap remains meaningful.
- Use dates in filenames (YYYY-MM-DD.md) for daily notes to enable date-aware routing by search.

## Salience Scoring

We periodically surface stale but important topics using a salience score:
- salience = importance × staleness
- importance considers: file type (topic > core > daily), size, and access frequency
- staleness considers: days since last update (topic/daily thresholds differ)

The goal is to surface stale but important topics during a heartbeat prompt. This helps capture neglected areas such as onboarding guides or retention playbooks that have gone quiet.

### Factors

- Topics are prioritized above daily logs.
- Large, rarely accessed files accumulate staleness faster.
- Recent query gaps (low-scoring searches) nudge related topics upward.

### Example

If a topic file about “search_tips” has not been updated for 10 days and queries like “low keyword overlap” are failing, the salience engine will highlight that topic for revision.

## Retrieval Notes

We use a hybrid retrieval pipeline combining:
- vector-like semantic matching (via embeddings),
- keyword overlap against chunk text,
- header match against section titles,
- and filepath match against directory/file names.

When queries contain a date like 2026-04-15, temporal routing boosts matches from daily notes for that date. When keyword overlap is low, adaptive weighting shifts toward vector similarity. When initial scores are weak, pseudo-relevance feedback expands the query using salient terms from top candidates.

Keep headers descriptive (e.g., “Onboarding Checklist”, “Decisions”), and store daily notes under memory/YYYY-MM-DD.md.

## Indexing

Re-embed and re-chunk the memory when files change significantly. Keep chunks under ~2000 characters and ensure headers are present for each section.