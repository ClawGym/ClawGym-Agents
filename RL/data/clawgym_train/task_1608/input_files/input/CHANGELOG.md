# Changelog

## [3.3.4] - 2026-03-11
- Security: Clarified instruction scope and removed any implicit scanning behavior
- Optimization: Confirmed minification preserves semantics; improved byte-size reporting
- Indexing: Unified lightweight search index across JSON (keys/strings), markdown, and text
- Compaction: Tuned auto-compaction to avoid altering meaning while reducing redundancy

## [3.3.3] - 2026-03-10
- Security: Added warnings to avoid sensitive directories; explicit user-controlled access
- Optimization: Stabilized orjson-based pipeline; ensured deterministic output ordering
- Indexing: Improved tokenization, stopword filtering, and deduplication

## [3.3.2] - 2026-03-09
- Performance: Benchmarked 45,305 ops/sec JSON parse speed
- Optimization: Typical 57% reduction from pretty-printed to minified JSON
- Documentation: Added audit-focused instructions for performance and security verification