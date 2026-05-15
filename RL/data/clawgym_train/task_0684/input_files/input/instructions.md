Audience and tone
- Write for an analyst or engineering lead who wants concise, decision-ready findings.
- Use clear, neutral US English. Avoid hype and speculation; prefer verifiable facts.

Source selection and vetting
- Prioritize primary/official sources (e.g., EU Commission/Parliament, python.org, Brave docs/pricing pages, SearXNG documentation).
- Supplement with reputable secondary sources (e.g., Reuters, major tech publications, project GitHub/readthedocs).
- Do not use paywalled sources. Avoid sites with undisclosed AI-generated content or low editorial standards.
- Prefer the most recent updates when facts conflict; note the date and version where relevant.

Search approach
- Craft targeted queries with keywords, and when helpful, use site filters (e.g., site:ec.europa.eu, site:python.org, site:brave.com, site:docs.searxng.org).
- Collect up to 5 unique, high-signal results per query. Deduplicate by exact URL.
- Extract a brief, relevant snippet that supports your summary.

Raw results output (output/raw_results.jsonl)
- One JSON object per query (exactly one line per object).
- Schema:
  {"query": string, "fetched_at": ISO8601 UTC like 2026-04-19T12:34:56Z, "results": [up to 5 items of {"title": string, "url": string starting with http/https, "content": string snippet}]}
- Ensure fetched_at uses Z-suffixed UTC. No extra fields. No empty strings. URLs must be publicly accessible.

Report output (output/report.md)
- Start with a section titled exactly "## Methodology" explaining your search and source-vetting process.
- For each query (use the exact string), add a section "## {query}" with:
  - 3–5 concise bullet points (- prefix) summarizing key findings, each grounded in your sources.
  - A "### Sources" sub-section listing at least 2 distinct URLs, which must also appear in that query’s raw_results.jsonl entries (exact URL match).
- Keep sections focused; avoid repeating the same point.

Quality checklist before finalizing
- All queries from input/queries.json appear once in both raw_results.jsonl and report.md.
- No extra or misspelled queries.
- Each results list has 1–5 unique URLs with clear titles and informative snippets.
- Report bullets are factual, specific, and correspond to the cited sources.
- No paywalled links.