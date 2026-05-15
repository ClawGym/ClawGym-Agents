# Design Questions

TopicID: T3
Context: High read throughput for config endpoints; cache stampede during deploys; edge CDN plus in-app cache.
Question: When combining CDN and in-process caches, what's a sane invalidation strategy to avoid thundering herds?

Notes: Considering soft TTL with background refresh; stale-while-revalidate might help.

TopicID: T4
Context: Integration tests are flaky on ephemeral runners; retries hide real failures.
Question: What isolation strategies do you trust for stabilizing CI without masking issues?

Notes: Suspect Docker-in-Docker overhead, clock skew.
