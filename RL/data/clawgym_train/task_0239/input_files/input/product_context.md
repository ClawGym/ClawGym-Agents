Project: Checkout microservice (Golang)

Summary:
- Language/stack: Go service exposing REST endpoints for e-commerce checkout and subscription management.
- Payment methods: Card-not-present (e-commerce) credit/debit cards via a third-party processor; US ACH debits authorized online; limited EU card transactions.
- Data handling: We do NOT store full PAN; we receive tokens and store last4, card brand, and expiration month/year. ACH routing/account numbers are tokenized by the provider; we store tokens and mandate IDs.
- Customers: US primary, some EU customers (billing addresses and cards issued in EU).
- Authentication: We can support 3-D Secure or similar flows via the processor when required.
- Future consideration: Scheduled payments and retries (dunning) for subscriptions.
- Goal: Identify key compliance standards/regulations that likely apply (or require coordination with legal) and assemble authoritative, official sources for review.
