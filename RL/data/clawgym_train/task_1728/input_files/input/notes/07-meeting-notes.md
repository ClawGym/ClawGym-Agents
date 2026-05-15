# Meeting Notes: Search Roadmap

Attendees:
- PM, Infra, Data, Search

Discussion:
- Keep fast keyword search as the default path for interactive use.
- Explore vector enrichment for difficult queries where exact match fails.
- Validate the embedding model on our own corpus before rollout.
- Caching of query results is acceptable with short TTL and jitter.

Decisions:
- Prototype hybrid ranking that blends BM25 with a small weight from vector similarity.
- Run an A/B test on a subset of traffic.
- Add guardrails to avoid surprising results.

Action items:
- Data: prepare evaluation set and baseline metrics.
- Search: implement embedding job for the top 10k docs.
- Infra: add a small cache with a 60–120s TTL and jitter.

Notes:
- Evaluate latency tradeoffs introduced by the embedding path.
- Document fallbacks when vector recall is low.

Follow-ups:
- Schedule a review in two weeks.