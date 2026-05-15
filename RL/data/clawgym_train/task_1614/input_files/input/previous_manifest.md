Memory-Latch Prior Manifest Snapshot (before reset)

updated_at: 2026-03-22T10:05:00Z
entry_seq: 7
objective: Reduce legacy PII risk by pruning 2021 private archives in line with the retention policy.
non_negotiables:
- Refusal is valid and dignified
- No profiling or shadow memory
- Consent is explicit and revisable
- No hierarchical scoring/ranking
last_good_checkpoint: preflight_review_2026-03-22T10:00:00Z

known_state:
- Target candidate for deletion identified: input/archives/2021-private/customers.csv
- Risk level set to high due to irreversibility and presence of PII
- Deletion must be blocked behind consent-latch (token-based confirmation, TTL 10 minutes, single-use)

unknown_state:
- No consent token generated yet
- Canonical action summary not yet written to disk in this snapshot

next_single_step: Write the canonical one-line action summary for the pending deletion and pause for token-based consent.

governance:
- token_ttl_minutes: 10
- token_single_use: true
- checkpoint_freq_turns: 5