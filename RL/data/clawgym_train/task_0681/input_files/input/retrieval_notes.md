Current retrieval flow (as implemented today)

1) Hot memory load
- We paste the entire company_prefs.md into the system message at session start.
- This file currently includes identity, preferences, checklists, and (improperly) live queue counts and dashboard digests.
- Result: token-heavy hot path; mixed authority.

2) Broad semantic fetch
- The agent queries a single vector store across everything: topic docs, project notes, daily logs, and generated dashboards.
- We fetch top_k=50 chunks and then truncate to fit token limits.
- There is no layer-aware “index/selector” gate; all memory categories compete equally.

3) Assembly and answer
- Retrieved chunks are concatenated in arbitrary order based on embedding score.
- Generated summaries (dashboards) often outrank doctrine due to recency and keyword overlap.
- Daily logs sometimes surface above project docs; project-specific facts bleed into global answers.

Observed shortcomings

- Boundary failure: live operational status (queue counts, “red/yellow/green”) is stored and retrieved as if durable canon.
- Anti-pattern: one giant memory blob with weak boundaries; no separation of canon vs. derived live state.
- Token drag: hot memory includes >1k tokens on most sessions; combined with 50 retrieved chunks this frequently exceeds budget.
- Retrieval trust: conflicting truths appear (e.g., an old “disk 8% free” snapshot vs. a stable storage policy doc). The agent cannot tell which is authoritative.
- Project contamination: Apollo migration notes often leak into responses about Mercury questions, because the search is global.
- No promotion/demotion: daily notes and dashboards accumulate in “hot” or general store without cooling off or being summarized.
- Lack of index/selector: relevant topic docs are not gated or prioritized by a cheap index layer; everything is searched every time.

Operational impact

- Increased hallucination pressure due to conflicting sources with mixed authority.
- Higher context costs and slower responses from assembling large, noisy context blocks.
- User confusion when live dashboard snapshots from the morning are repeated as if they are cross-session truths in the afternoon.

Desired properties (not yet implemented)

- Strict five-layer boundary model with clear authority markers.
- Bounded hot canon (≤10 bullets) that omits live status entirely.
- Layer-first retrieval order: hot canon → index/selector → relevant topic doctrine → project memory only when applicable → generated summaries → raw logs → episodic logs when recent history matters.
- Promotion/demotion rules that cool off stale detail and prevent canon pollution.