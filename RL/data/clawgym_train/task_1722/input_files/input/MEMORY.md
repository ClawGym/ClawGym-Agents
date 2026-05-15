# Local Memory Search — Internal Notes

Purpose
- Provide a lightweight, offline semantic search over our notes.
- Return exact, citable snippets with file paths and line numbers.

Scope of indexing
- Search the following sources:
- input/MEMORY.md and input/memory/*.md as the primary corpus.

Indexing algorithm (overview)
- Chunking: Chunk size is 500 characters per block to balance context and precision.
- Line tracking: We preserve line numbers and count each file’s lines starting at 1.
- Embeddings: When available, generate embeddings locally and use cosine similarity.
- TF-IDF fallback: If embeddings are unavailable, fall back to TF-IDF scoring.
- Ranking: Combine relevance signals to rank results and return the top snippets.

Implementation details
- Embedding model: nomic-embed-text (local, via Ollama).
- Similarity: cosine similarity for embeddings-based scoring.
- Storage: The index is stored at ~/.openclaw/memory_index.json on the local machine.
- Workspace conventions: We treat ~/.openclaw/workspace as the canonical working directory for memory notes.

Snippet format and citations
- Each returned snippet includes file, start_line, end_line, and an exact snippet string.
- Citations use the path plus line span format: input/path.md#<start>-<end>.
- The snippet text must be verbatim from the referenced lines.

Operational notes
- The operational SLOs and escalation steps are defined in input/memory/ops.md.
- If a search index build fails, follow the incident handling procedures and pager escalation.

Roadmap context
- The Q3 roadmap emphasizes offline mode, faster index builds, and clearer line-based citations.
- See input/memory/product.md for Q3 priorities, priorities ordering, and rationale.

Compliance and lifecycle
- Default retention is 90 days for stored indices and embeddings unless overridden.
- Deletion: Remove ~/.openclaw/memory_index.json and rebuild to confirm purge.
- Detailed retention and deletion procedures appear in input/memory/compliance.md.

Testing guidance
- Validate that line numbers start at 1 for every file.
- Confirm that both TF-IDF and embeddings produce consistent top-3 snippet ordering on core queries.

Known limitations
- Chunk boundaries may split headings; citation still references exact line ranges.
- TF-IDF may over-weight frequent terms; embeddings mitigate this when available.

Maintenance
- Update this document when chunk size, TF-IDF weighting, or embeddings model changes.
- Keep references to operations, product plans, and compliance current and consistent.