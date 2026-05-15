## [2026-04-08] Emergent capability: Schema Debugging Accelerator
**Category**: emergent_capability
**Priority**: medium
**Status**: pending
**Skills combined**: schema-markup + roi
**What emerged**: Generate JSON-LD plus targeted devtips from roi to reduce validation cycles and fix common schema errors faster.
**How it works**: schema-markup drafts compliant JSON-LD; roi provides debugging steps, anti-patterns, and validation guidance; combined output shortens fix time.
**Evidence**: Reduced warnings from 12 → 3 across 3 pages in 15 minutes (no secrets logged).
**Promotion**: → COMBINATIONS.md when proven 3+ times

## [2026-04-12] Emergent capability: Schema Fix Playbook Generator
**Category**: emergent_capability
**Priority**: high
**Status**: pending
**Skills combined**: schema-markup + roi
**What emerged**: Auto-generated per-type fix playbooks (required fields, ISO date formats, URL checks) alongside ready-to-embed JSON-LD.
**How it works**: schema-markup enumerates properties; roi injects reference snippets for debugging and validation workflows.
**Evidence**: 5 articles validated with zero critical errors; time-to-fix down ~40%.
**Promotion**: → COMBINATIONS.md when proven 3+ times

## [2026-04-15] Emergent capability: Rapid Validator-Ready Templates
**Category**: emergent_capability
**Priority**: medium
**Status**: pending
**Skills combined**: schema-markup + roi
**What emerged**: Pre-bundled JSON-LD templates with inline notes for Rich Results Test readiness.
**How it works**: schema-markup assembles JSON-LD; roi annotates with quickstart and troubleshooting cues; outputs ready for validation.
**Evidence**: 6 templates passed Rich Results Test on first attempt; no sensitive data logged.
**Promotion**: → COMBINATIONS.md when proven 3+ times

## [2026-04-10] Emergent capability: News-Triggered FAQ Schema Update
**Category**: emergent_capability
**Priority**: low
**Status**: pending
**Skills combined**: searxng + schema-markup
**What emerged**: Draft FAQPage markup keyed to trending queries from news category.
**How it works**: searxng identifies hot questions → schema-markup outputs compliant Q&A JSON-LD.
**Evidence**: 2 pages updated; validation clean; impact TBD.
**Promotion**: → COMBINATIONS.md when proven 3+ times

## [2026-04-14] Emergent capability: Fresh Query → FAQ Pipeline
**Category**: emergent_capability
**Priority**: medium
**Status**: pending
**Skills combined**: searxng + schema-markup
**What emerged**: Pipeline for mapping new queries into FAQPage JSON-LD drafts with review flags.
**How it works**: searxng discovers queries; schema-markup drafts structured data; human review before publish.
**Evidence**: 1 draft set created; awaiting editorial approval.
**Promotion**: → COMBINATIONS.md when proven 3+ times

## [2026-04-09] Failed combination: Unstructured ROI Search Feed
**Category**: emergent_capability_failed
**Priority**: low
**Status**: resolved
**Skills combined**: searxng + roi
**Why it failed**: Reference outputs did not map directly to structured schema fields; signals were inconsistent for automation.
**Prevention**: Use roi for documentation guidance only; avoid feeding raw search results into reference workflows.

## [2026-04-11] Failed combination: Drifted FAQ Markup from News Noise
**Category**: emergent_capability_failed
**Priority**: low
**Status**: resolved
**Skills combined**: searxng + schema-markup
**Why it failed**: Some trending queries were not relevant to page content, violating accuracy-first principle.
**Prevention**: Enforce content-matching checks before generating FAQPage schema; editorial review required.