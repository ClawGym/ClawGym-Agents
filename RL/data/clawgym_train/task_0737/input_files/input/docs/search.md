# Search Capabilities

The Acme Dev Platform provides powerful search features combining keyword relevance and semantic understanding. This guide explains keyword search, semantic search, and hybrid modes with reranking, plus tips for excerpt retrieval and tuning.

---

## Keyword search (BM25)

- Optimized for exact term matches and field weights.
- Ideal for precise queries like “rate limiting headers” or “Retry-After meaning”.
- Use when you expect exact term overlap with documents.

API:
```
GET /v1/search?query=rate%20limiting&mode=keyword
```

Response includes:
- hits[].path — Document path, e.g., docs/rate-limiting.md
- hits[].score — BM25 relevance score
- hits[].positions — Matching term positions (when enabled)

---

## Semantic search

Semantic search uses vector embeddings to find meaningfully related documents even when exact terms differ.

- Good for broad or conceptual queries like “authentication flow for web apps”.
- Embeddings are generated from document text and queries.
- Vector distance determines initial candidate set.

API:
```
GET /v1/search?query=authentication%20flow&mode=semantic
```

Notes:
- Fresh embeddings are required for new or changed documents.
- If embeddings are stale, relevance may degrade until the next embed job completes.

---

## Hybrid search and reranking

Hybrid search combines keyword and semantic search:
1) Run both keyword and semantic queries.
2) Merge candidates.
3) Rerank using a cross-encoder or learning-to-rank model.

API:
```
GET /v1/search?query=rate%20limiting&mode=hybrid&top_k=5
```

Reranking signals:
- Keyword score (BM25)
- Vector similarity
- Field boosts (e.g., title > body)
- Freshness and document popularity (optional)

Result quality:
- Hybrid generally outperforms keyword-only or semantic-only for most queries.
- Tune weights depending on your corpus and user behavior.

---

## Excerpts and citations

You can retrieve targeted excerpts using a `path:line:length` style to cite documentation precisely in support answers.

Example:
- Path: docs/authentication.md
- Start line: 120
- Length: 40

Use your tooling to fetch and display a 40-line excerpt around the matched section:
```
docs/authentication.md:120 (next 40 lines)
```

Tips:
- Start a few lines before the exact match to provide context.
- Always display the source as `[source: path:line]` for support transparency.

---

## Field boosts and configuration

- title: 3.0
- headings: 2.0
- body: 1.0
- path: 0.5 (exact path matches can help disambiguate)

Adjust these weights to fit your corpus.

---

## Query guidelines

- Keep queries short and specific for keyword mode.
- Use natural language for semantic search when term overlap is low.
- In hybrid mode, consider adding synonyms or alternate phrasings.

Examples:
- “API token scopes”
- “index update incremental vs rebuild”
- “semantic search reranking signals”

---

## Troubleshooting

- No results in semantic mode: Ensure embeddings are built and the `embedding` field exists.
- Keyword beats semantic unexpectedly: Check analyzer settings (stemming, stopwords).
- Slow queries: Reduce top_k or disable positions; ensure index is warmed.

---

## Monitoring search quality

- Track CTR and session success per mode (keyword, semantic, hybrid).
- Periodically audit top queries to adjust boosts and reranking weights.
- Log false negatives and add synonyms or FAQs where needed.

---

# End of search capabilities