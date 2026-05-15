## Research
### OpenClaw agent workflow: local KM sync performance results
We tested and measured km sync performance on a sample workspace with 137 entries, running three times on cold and warm caches. Data shows a 1.8x speedup after adding hash-based dedup and skipping unchanged content. Verified results: cold run 11.2s → warm run 6.1s. Benchmark notes: automation overhead was negligible; I/O dominated. This is for the OpenClaw skill that organizes memory into folders.

### Benchmark: Mistral vs Claude function-calling accuracy
Research benchmark comparing function-calling reliability across models (Mistral, Claude, GPT). Tested on 42 prompts requiring structured JSON calls. Measured pass@1: Claude 86%, Mistral 78%, GPT-4o 91%. Verified with strict schema validation and retries disabled. Key insight: adding explicit tool descriptions improved Mistral by ~6pp. Tags: benchmark, AI, function-calling.

## Decision
### Chose hash-suffixed filenames to avoid collisions
We determined that filename collisions were causing overwrites when titles matched. Decision: add an 8-character hash suffix (MD5 of title+date+body snippet) to every output file. Selected this approach over counters because it’s deterministic and idempotent for OpenClaw knowledge syncs. Impact: significant reduction in accidental overwrites; cleanup remains simple.

## Insight
### Cost routing: free-tier fallbacks inflate errors
Observed pattern during weekend traffic: enabling free tier fallbacks for token routing reduced direct dollar cost but increased failures and retries by ~14%. The insight is that “saving” on budget can degrade reliability and throughput, ultimately increasing total processing time. Likely better to cap free usage and prefer stable low-cost providers. Keywords: cost, budget, optimization, routing.

## Pattern
### Recurring failure mode: stale sync state causes orphans
A recurring pattern: when the local sync state isn’t updated (crash mid-run), subsequent runs leave orphaned files that aren’t in the map. This shows up as duplicated knowledge under different hashes. The fix is to run cleanup, then a full sync. Preventative: write state atomically and checkpoint progress. Affects OpenClaw workflow reliability and developer trust.