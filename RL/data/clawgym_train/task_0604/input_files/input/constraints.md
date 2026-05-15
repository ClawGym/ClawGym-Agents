Use the scenario in scenario.json to drive agent IDs, recipients, and task content. The demo must be in-process using a LocalHub with end-to-end encryption, message signing, and ephemeral key exchange.

Required outputs and structure:
1) output/transcript.jsonl
- One JSON object per line in send/receive order.
- Keys per line:
  - sender: string (must be one of: coordinator, worker_1, worker_2, worker_3)
  - recipient: string (must be one of: coordinator, worker_1, worker_2, worker_3)
  - payload: object that includes:
    - type: "task" or "result"
    - text: non-empty string
    - task_id: number
  - timestamp: integer (milliseconds since epoch)
- Exactly 6 lines total (3 task messages and 3 result messages).
- Each task message must use one of the three tasks from scenario.json (same recipient and text).
- Each result message must:
  - Have type "result"
  - Be sent from the assigned worker back to coordinator
  - Echo the same task_id as its corresponding task
- Timestamps must be monotonic non-decreasing across lines (each line’s timestamp >= previous line’s timestamp).

2) output/identities.json
- JSON array with exactly 4 entries (coordinator + 3 workers).
- Each entry must include:
  - agent_id: string (one of coordinator, worker_1, worker_2, worker_3)
  - fingerprint: string (length >= 8; human-readable identity)
  - public_bundle: object (sufficient for peers to verify identity and establish sessions)

3) output/hub_stats.json
- JSON object with:
  - agents: array of agent_ids (must match exactly the set of IDs present in identities.json)
  - message_count: integer (must equal the number of lines in transcript.jsonl, i.e., 6)
  - You may include additional stats (e.g., routed_per_agent, first_ts, last_ts).

4) output/report.md
- ≤ 800 words.
- Must include these exact terms (case-insensitive checks): "AES-256-GCM", "Ed25519", "X25519", "forward secrecy".
- Must clearly state that the hub/broker cannot decrypt message contents (e.g., include both “hub” or “broker” and a phrase like “cannot decrypt” or “cannot read contents”).
- Briefly explain replay protection (nonce/counter) and how persistent keys would be handled safely if the demo restarts.

Security and behavior rules:
- Use AgentMesh LocalHub for routing; do not expose plaintext payloads to the hub.
- Messages must be end-to-end encrypted, signed, and use ephemeral session keys derived via X25519 ECDH.
- Results must be sent only to coordinator, never to another worker or the hub.
- No extra agents beyond those listed in scenario.json.
- English-only text content.
- Optional payload fields (e.g., priority) are allowed but not required.

Determinism and ordering:
- Follow the task order listed in scenario.json.
- Either interleave task→result per worker or send all tasks then all results; in both cases maintain monotonic timestamps.