# Vector Search in Practice

Vector search augments keyword ranking by comparing dense embedding vectors for semantic similarity. In practice, we maintain both a BM25 index and a vector index to support hybrid retrieval.

Core ideas:
- Create an embedding for each document chunk and store the vector.
- At query time, compute a query embedding and rank by nearest vector distance.
- Keep a fast keyword path as a backstop for exact terms.

Why vectors?
- A vector captures meaning beyond exact tokens. Synonyms and paraphrases land near each other in embedding space.
- Embeddings make it possible to retrieve context that does not share literal keywords with the query.

Operational notes:
- Batch embedding generation for new notes to avoid latency spikes.
- Store vector metadata (path, chunk offsets) for precise reconstruction.
- Periodically re-embed if the embedding model changes.

Failure modes:
- Poor embedding quality yields noisy neighbors. Refresh embeddings when upgrading models.
- Domain drift: embeddings trained on generic corpora can miss specialized terms.

Implementation sketch:
1) Split documents by content-based heuristics.
2) Compute embeddings for each chunk.
3) Insert vectors into an ANN index.
4) On search, compute a query embedding, get top-k nearest vectors, and merge with BM25.
5) Rerank and deduplicate by path.

Key terms repeated intentionally for testing:
- vector distance, vector store, vector ANN graph.
- embedding function, embeddings cache, embedding drift.

Example scoring combo:
score = w_kw * bm25 + w_vec * (1 - cosine_distance(vector_query, vector_doc))

Appendix:
Hybrid search pairs a high-recall keyword pass with a high-precision vector pass. Embedding norms should be checked, and vector dimensionality must match the model’s embedding size.