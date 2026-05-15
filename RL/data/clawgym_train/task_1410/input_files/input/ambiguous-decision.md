# Architectural Decision: Readiness Score Computation & Data Flow

## Problem
We must decide how to compute and serve the readiness score and criteria breakdown for a given service and ref (branch or tag). The current implementation computes on read (request time) using an in-memory cache and file-backed JSON storage. As we approach MVP, we need a more intentional design that meets performance, freshness, and reliability targets while keeping complexity manageable for a small team and short timeline.

## Constraints
- Timeline: 3 weeks MVP; keep complexity low and changes reversible.
- Team: 3 engineers; limited ops bandwidth.
- Traffic: ~10–20 internal users/day, with occasional spikes to 50 concurrent during release hours.
- Freshness: Inputs should be no older than 2 minutes for “current readiness.”
- Performance: p95 < 300ms for GET /readiness under 50 concurrent requests.
- Reliability: 99.5% monthly SLO, graceful degradation if a signal is missing.
- Storage: MVP may use a lightweight embedded or file-backed store as long as querying and 30-day retention are feasible.

## Inputs
- Build summary (pass/fail boolean + timestamp)
- Test coverage summary (percentage + timestamp)
- Performance budget check (boolean per budget + timestamp)
- Blocking issues count (integer + timestamp)
- Optional manual override (boolean + reason + user + timestamp)

## Evaluation Criteria
- Complexity/maintainability (small team, small files, types-first).
- Performance (latency and concurrency).
- Data freshness guarantees.
- Correctness determinism (same inputs → same score).
- Reliability and graceful failure handling.
- Ease of testing (unit and integration).
- Migration path beyond MVP (reversible choices preferred).

## Options to Explore (Universes)
- Universe A: Compute-on-read with memoized cache
  - Recompute readiness at request time using the latest ingested inputs; cache results by (service, ref) with short TTL.
- Universe B: Scheduled precomputation with materialized views
  - A background job recomputes readiness at fixed intervals and writes materialized snapshots; API serves the latest snapshot.
- Universe C: Event-driven incremental updates
  - On ingestion events (new build, new coverage), incrementally update a stored readiness snapshot; API is read-only against the snapshot.
- Universe D: Hybrid cache with smart invalidation
  - Cache readiness per (service, ref) and invalidate/refresh on ingestion or TTL expiry; combine fast reads with bounded staleness.

Please evaluate at least three of these universes with clear trade-offs and recommend one (or a hybrid) aligned with the MVP timeline and our non-functional requirements.

---