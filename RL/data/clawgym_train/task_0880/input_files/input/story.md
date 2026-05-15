In August 2025, a PagerDuty alert woke me at 1:14 a.m. Our signing API saw a burst of calls from an IP outside our allowlist. It hit a staging key, not production, and no funds moved. But that 7-minute window was enough to make me admit something: keeping any private key material on internet-connected servers was a bet we didn’t need to make.

We made a hard pivot in September: keys would never live on our servers again. We rebuilt our flow around an offline-first model. Users (and our internal operators) would hold BIP-39 seed phrases (12 or 24 words) locally. Signing happened on a device they controlled. The server would only see signed payloads, never private keys.

We shipped EVM first in October with chain-specific derivation. In December, we added Bitcoin (PSBT) and Solana. For higher-risk accounts, we supported hardware wallets and air-gapped QR signing. It wasn’t frictionless at first—onboarding got ~3 minutes slower—but it was honest friction that customers understood.

Q1 2026 was our proof point. We stored zero key material on our infrastructure. Security-related tickets dropped from 14 per quarter (Q2–Q3 2025 average) to 5. “Unauthorized access” tickets went to 0. Our NPS moved from 43 to 58. Two clients who were about to churn over security concerns renewed.

The biggest change wasn’t technical. It was trust. When we could say, “Your keys never touch our servers,” conversations got calmer. One client’s FinOps lead told me, “I sleep better knowing a compromised server can’t touch our funds.” I do, too.