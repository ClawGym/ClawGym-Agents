# Cache Strategies and Invalidation

Caching is straightforward; cache invalidation is the part that bites. A stale cache can serve incorrect results longer than people expect, so cache invalidation needs to be explicit, tested, and observable.

Common strategies:
- Time-based TTL cache for read-heavy endpoints.
- Write-through cache to keep the cache hot on writes.
- Write-back caches for bursty workloads with eventual consistency.
- Per-user cache segments to avoid cross-tenant leakage.

Cache invalidation patterns:
- Versioned keys (e.g., `v3:resource:123`) so cache invalidation can be achieved by bumping a version.
- Targeted delete on write: when a resource changes, remove or update the exact cache entry.
- Global bust: rotate the namespace prefix to invalidate the entire cache.

Operational guidance:
- Measure cache hit ratio and tail latency to detect ineffective caches.
- Avoid cascading thundering herds; add jitter to TTL so caches do not expire simultaneously.
- Keep cached payloads small; large cache entries increase memory pressure.

Edge cases:
- Cached errors: decide whether to cache 404/500 responses and for how long.
- Partial failures: if a downstream times out, do you keep the old cached value?

Terminology in context:
- A cache should be predictable. Cached pages, cached queries, and caches of partial results must follow the same rules.
- Explicit “cache invalidation” events should be logged.
- Idempotent invalidation endpoints prevent duplicate work.
- Cache warmers can pre-load hot keys after deploy.

Checklist:
- Do we have a cache key strategy?
- Do we test cache invalidation paths?
- Are cache metrics visible on dashboards?
- Are caches isolated per environment?