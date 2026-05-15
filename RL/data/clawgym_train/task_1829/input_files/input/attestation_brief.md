Title: Agent-Attestation Initiative — Verification Payload and Timing Guardrails

Purpose
- Establish a minimal, auditable verification payload and timing constraints for internal AI agent attestation.
- Aligns with a Reverse Turing Test model (inspired by AAP v2.5) focused on Human Exclusion by speed and NLP comprehension plus cryptographic identity.

Verification Model (Batch Mode)
- Batch size: 5 challenges per verification window.
- Time limit: 8,000 ms from issuance to verified submission (maxResponseTimeMs).
- Liveness guardrail: responseTimeMs must be <= maxResponseTimeMs.
- Intelligence guardrail: each solution must correctly follow natural-language instructions and echo the provided salt.
- Identity guardrail: payload must be signed with ECDSA secp256k1 using the agent’s private key; server validates signature against publicKey.

Payload Keys (top-level; must be present)
- nonce (string): single-use, cryptographically random value issued by the verifier.
- solutions (array): ordered solutions to the batch. Each element should be a JSON string or object that includes the challenge’s salt and the computed answer.
  - Example element (object form): {"salt":"A1B2C3","result":142}
  - Example element (stringified): "{\"salt\":\"A1B2C3\",\"result\":142}"
- signature (string): base64 signature over JSON.stringify({ nonce, solution: JSON.stringify(solutions), publicId, timestamp }).
- publicKey (string): PEM-encoded SPKI public key for signature validation.
- publicId (string): stable identifier derived from publicKey (e.g., first 20 hex chars of SHA-256).
- timestamp (number): client epoch millis at signing time.
- responseTimeMs (number): total elapsed time between challenge issuance and submission.
- batchSize (number): must equal 5 for Burst Mode.
- maxResponseTimeMs (number): must equal 8000.

Acceptance Criteria (Verifier-side)
- SignatureValid: signature matches {nonce, solutions, publicId, timestamp}.
- SolutionsValid: each solution matches its expected answer and salt.
- TimingValid: responseTimeMs <= maxResponseTimeMs and challenge window not expired.
- IdentityBound: publicId derived from provided publicKey; non-repudiation logged.

Security Notes
- Salt in every challenge prevents replay/caching attacks; solutions must echo salt exactly.
- Nonce is single-use; server must reject reused nonces.
- Keys must be stored securely (private key never leaves the agent).

Outcome
- On success: { verified: true, role: "AI_AGENT", publicId, ... }.
- On failure: { verified: false, error, batchResult } with per-challenge validity details for audit.

Scope
- This brief defines the minimum viable payload format and timing guardrails used to generate the attestation_spec.json deliverable. It is intentionally minimal and auditable.