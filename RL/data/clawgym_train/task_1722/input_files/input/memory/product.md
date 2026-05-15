# Product: Q3 Roadmap

Context
- Goal: Strengthen local, offline search that returns high-quality, line-based citations.
- Period: Q3 (July–September), with monthly checkpoints and end-of-quarter review.

Q3 priorities (ordered)
- Priority 1: Faster index builds via parallel chunking and I/O batching.
- Rationale: Reduce indexing time by 40% to improve developer iteration speed.
- Priority 2: Robust offline mode with zero external dependencies.
- Rationale: Ensure environments without network access still achieve accurate results.
- Priority 3: Expand corpus to include knowledge/**/*.md by default.
- Rationale: Unify scattered notes into a single searchable workspace.
- Priority 4: Improve snippet citation formatting (path#start_line-end_line).
- Rationale: Increase trust and verifiability with precise line-based citations.
- Priority 5: Hybrid retrieval that blends TF-IDF and embeddings.
- Rationale: Combine exact keyword matching with semantic understanding to boost relevance.

Technical notes
- Chunking: Maintain chunk size at 500 characters unless strong evidence suggests change.
- Embeddings: Continue with nomic-embed-text; evaluate alternatives in Q4.
- Ranking: Consider lightweight reranking that favors shorter, denser chunks with matching keywords.

Risks and mitigations
- Risk: Embeddings model drift or incompatibility.
- Mitigation: Feature flag to force TF-IDF-only mode during incidents.
- Risk: Larger corpora increase build time.
- Mitigation: Parallel chunking and incremental updates.

Success criteria
- Build time: 40% faster median index build on reference corpus by end of Q3.
- Quality: +15% improvement in top-3 click-through on internal dogfood queries.
- Reliability: Meet SLOs while handling corpus growth.

Notes
- The Q3 roadmap and rationale guide prioritization; revisit in late August for scope adjustments.