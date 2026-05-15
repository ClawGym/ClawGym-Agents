# Indexing and Update Procedures

This guide explains how to create, maintain, and perform an index update for content used by the Acme Dev Platform’s search services. It covers initial indexing, incremental updates, rebuilds, and blue/green cutovers.

---

## Concepts

- Index: A logical collection of documents optimized for search.
- Shards: Horizontal partitions of the index for scalability.
- Replicas: Redundant copies for availability and fast reads.
- Index schema: Field definitions, analyzers, and vector configurations.

---

## Initial indexing

1) Create the index:
```
POST /v1/indexes
{
  "name": "docs",
  "schema": {
    "fields": [
      {"name": "title", "type": "text"},
      {"name": "body", "type": "text"},
      {"name": "path", "type": "keyword"},
      {"name": "embedding", "type": "vector", "dims": 1024}
    ]
  }
}
```

2) Ingest documents in batches:
```
POST /v1/indexes/{id}/documents:batch
[
  { "id": "doc-1", "title": "Auth", "body": "...", "path": "docs/authentication.md" },
  { "id": "doc-2", "title": "Rate limiting", "body": "...", "path": "docs/rate-limiting.md" }
]
```

3) Build embeddings (if semantic search is enabled):
```
POST /v1/indexes/{id}:embed
```

---

## Incremental index update

An incremental index update modifies only the documents that changed, without rebuilding everything.

When to use:
- Nightly syncs
- On content edits
- After small schema-compatible changes

How to perform an incremental index update:
1) Detect changed docs (by checksum or updated_at).
2) Upsert only the changed docs:
```
POST /v1/indexes/{id}/documents:upsert
[
  { "id": "doc-2", "body": "new content...", "path": "docs/rate-limiting.md" }
]
```
3) Re-embed changed docs (if using semantic search):
```
POST /v1/indexes/{id}:embed?mode=incremental
```
4) Validate counts and sample queries before marking the update complete.

Gotcha:
- If the index schema changed in incompatible ways, an incremental index update may fail. See “Rebuild.”

---

## Full rebuild (reindex)

Perform a full rebuild when:
- Breaking schema changes are introduced
- Vector dimension changes
- Analyzer or tokenization changes require reprocessing

Steps:
1) Create a new index version (e.g., docs_v2).
2) Ingest all documents into docs_v2.
3) Build embeddings and warm caches.
4) Switch traffic (blue/green cutover) to the new index:
```
POST /v1/indexes/{alias}:switch
{
  "to": "docs_v2"
}
```
5) Decommission the old index after validation.

---

## Triggers for index update

- Webhooks: When content changes in your CMS, fire a webhook to /v1/indexes/{id}/documents:upsert.
- Scheduled jobs: Nightly tasks compute diffs and perform an index update automatically.
- Manual CLI:
```
acme index update --index docs --changed-since "2026-02-01T00:00:00Z"
```

---

## Monitoring an index update

- /v1/indexes/{id}/jobs returns recent tasks with status:
  - PENDING, RUNNING, SUCCESS, FAILED
- Inspect job logs for embedding or analyzer errors.
- Verify “document_count” and sample search results after each index update.

---

## Rolling back

If an index update degrades relevance:
- Switch alias back to the previous index version:
```
POST /v1/indexes/{alias}:switch
{
  "to": "docs_v1"
}
```
- Investigate schema, analyzer, or embedding changes.
- Re-run the index update after fixes.

---

## Performance considerations

- Batch sizes: 200–1,000 documents per request are typical.
- Parallelism: Up to 4 concurrent upsert streams per index is recommended.
- Embeddings: Throttle embedding jobs to avoid rate limits with the embedding provider.

---

## Common errors and resolutions

- 400 schema_incompatible: A field changed type; perform a rebuild instead of an incremental index update.
- 409 version_conflict: Document updated concurrently; retry with backoff.
- 429 rate_limited: Respect Retry-After and slow down your index update pipeline.

---

## Checklist for every index update

- [ ] Only changed docs are upserted
- [ ] Embeddings refreshed for changed docs
- [ ] Sample searches validated (keyword and semantic)
- [ ] Monitoring shows no job failures
- [ ] Blue/green switch performed safely (if applicable)

---

# End of indexing and update procedures