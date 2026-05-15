# Vault Module (Move) — Source Excerpt

This is a simplified Move module implementing a basic vault with deposit/withdraw operations, a simple classifier utility, and increment/decrement helpers. Use this excerpt for test-writing context and security review.

```move
// sources/vault.move

module 0x42::vault {
    // Error codes
    const EInvalidInput: u64 = 0;
    const EInsufficientBalance: u64 = 1;

    // Increase the balance by a positive amount
    public fun deposit(balance: &mut u64, amount: u64) {
        assert!(amount > 0, EInvalidInput);
        *balance = *balance + amount;
    }

    // Decrease the balance by amount, fails if amount > balance
    public fun withdraw(balance: &mut u64, amount: u64) {
        assert!(*balance >= amount, EInsufficientBalance); // Failure path for insufficient funds
        *balance = *balance - amount;
    }

    // Return a simple class for a value: 0 → 0, (0 < v < 100) → 1, otherwise → 2
    public fun classify(value: u64): u8 {
        if (value == 0) {
            0
        } else if (value < 100) {
            1
        } else {
            2
        }
    }

    // Decrement a number
    public fun decrement(x: &mut u64) {
        *x = *x - 1;
    }

    // Increment a number
    public fun increment(x: &mut u64) {
        *x = *x + 1;
    }
}
```

Notes for tests and coverage:
- The LCOV data indicates that `decrement()` was never called by tests (uncalled function).
- The `classify()` function has multiple branches; at least one branch path (e.g., `value == 0` or `value < 100`) was not taken in the current suite.
- The `withdraw()` function includes an assertion guarded by `EInsufficientBalance`. The failure path is currently untested. Add a test with `#[expected_failure(abort_code = 0x42::vault::EInsufficientBalance)]` (or unqualified `EInsufficientBalance` if in scope) to ensure the insufficient balance path is explicitly exercised.

Security considerations to keep in mind when writing tests:
- Access control: Functions are public; ensure state mutation is appropriate for public exposure.
- Integer safety: Subtraction in `withdraw` and `decrement` can underflow if assertions are bypassed or if misuse occurs; tests should include boundary values.
- Economic invariant: After any sequence of deposits and withdrawals, the balance must remain ≥ 0 and consistent with operations.
- DoS vectors: There are no loops or unbounded operations here; low DoS risk in this excerpt.