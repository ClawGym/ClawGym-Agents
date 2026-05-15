Project: Defensive Refactor of Banking Module (Design-by-Contract)

Goal
Refactor a small Python banking module using defensive programming with a clear separation between exceptions (for user/environment errors) and assertions (for internal correctness). Implement design-by-contract elements: explicit preconditions (validated with exceptions at public boundaries), postconditions (assertions after state changes), and invariants (assertions about persistent object state).

Input Files to Read
- input/brief.md (this file)
- input/bank_initial.py (current, flawed implementation)

Deliverables to Produce
Write all outputs under output/:

1) output/src/bank.py — Refactored module
   Requirements:
   - Public API error handling using exceptions:
     - deposit(amount), withdraw(amount), and transfer(from_acct, to_acct, amount) must validate user/environment errors using exceptions (e.g., raise ValueError for non-positive amounts, insufficient funds, wrong types/instances).
     - Do not use assertions for input validation, authentication, or security.
   - Internal correctness using assertions:
     - Use assert statements to enforce class invariants, loop/data invariants (if applicable), and postconditions immediately after state mutations.
     - Provide descriptive assertion messages that include actual runtime values (e.g., f"expected new balance {old_balance + amount}, got {self.balance}").
     - Add a _check_invariants(self) method that verifies:
       - balance is an integer or Decimal (no floats preferred) and >= 0
       - owner is a non-empty string
       - transactions list integrity
     - Call _check_invariants() after each public mutation (deposit, withdraw, and after transfer affects both accounts).
     - Include at least one expensive invariant guarded by if __debug__: (e.g., O(n) check such as sum(txn amounts) == balance, or cross-check transaction history consistency) so it runs only in debug mode.
   - Postconditions:
     - After deposit: assert self.balance == old_balance + amount
     - After withdraw: assert self.balance == old_balance - amount
     - After transfer: assert total funds conservation (sum before == sum after). Use variables like old_total or similar to make this explicit.
   - Transfer:
     - Implement transfer(from_acct, to_acct, amount) as a function or a @staticmethod that:
       - Validates preconditions with exceptions (non-negative amount, from_acct != to_acct, sufficient funds, instances of BankAccount).
       - Preserves total funds; include a postcondition asserting conservation (no hidden fees).
   - Avoid assertion anti-patterns:
     - No side effects in assert expressions (e.g., no list.append() or I/O inside assert).
     - Do not catch AssertionError.
     - Do not use asserts for security (e.g., assert user.is_admin()) or input validation.
   - Implementation notes:
     - Standard library only; keep the module self-contained.
     - Prefer integers representing smallest currency unit (cents) or Decimal for monetary values; avoid floats in the final design.
     - Use clear, small helpers if needed. Keep cohesion high and interfaces simple.

2) output/tests/smoke.py — Minimal smoke tests (no third-party libs)
   Requirements:
   - Import the refactored bank module and construct BankAccount instances.
   - Exercise error paths:
     - deposit with invalid input (e.g., 0 or negative) should raise ValueError; verify with try/except ValueError.
     - withdraw with invalid input (e.g., negative or greater than balance) should raise ValueError; verify similarly.
   - Exercise a valid path:
     - Perform at least one valid transfer between two accounts and confirm resulting balances by print or simple checks.
   - Keep it runnable without extra tooling; do not rely on pytest or unittest, just simple try/except and prints.

3) output/README.md — Engineering note (concise but thorough)
   Requirements:
   - Explain your design choices: when you used exceptions vs assertions and why.
   - Describe implemented preconditions, postconditions, and invariants (design-by-contract).
   - Identify anti-patterns from the original code that you removed (e.g., side effects in asserts, catching AssertionError, security checks in asserts) and why they are harmful.
   - Explain how debug-only checks are organized with if __debug__: and which expensive invariant(s) are gated.
   - Length guidance: >= 800 characters. Include the keywords: preconditions, postconditions, invariants, anti-patterns, design-by-contract, assertions, exceptions.

Functional Requirements and Constraints
- BankAccount
  - Fields: owner (str), balance (int cents or Decimal), optional account_id (str), and a transactions list for history.
  - Public API: deposit(amount), withdraw(amount), get_balance() (returns numeric type used), and a transfer function accepting from_acct, to_acct, amount.
  - Invariants:
    - balance >= 0
    - owner is a non-empty string
    - transactions is a list of immutable tuples (type, amount, resulting_balance), where amount > 0 and resulting_balance >= 0
    - Expensive (debug-only) invariant: sum of signed transaction amounts equals current balance (treat deposit as +amount, withdraw as -amount).
- Error handling with exceptions:
  - deposit(amount):
    - Raise ValueError if amount is not positive or not a numeric type supported by your design.
  - withdraw(amount):
    - Raise ValueError if amount is not positive or if amount > balance.
  - transfer(from_acct, to_acct, amount):
    - Raise ValueError on invalid accounts, same-account transfer, non-positive amount, or insufficient funds.
- Assertions:
  - Use assert only for internal correctness checks: invariants and postconditions.
  - Provide detailed messages including actual values to aid debugging.

Anti-Patterns to Remove From Initial Code
- Using assert for user input validation in public methods.
- Side effects inside assert expressions (e.g., log.append(), file operations).
- Catching AssertionError to alter behavior.
- Asserting security/auth (assert user.is_admin()) or token checks.
- Empty or unhelpful assertion messages.

Style and Practical Notes
- Keep the code readable and small; prioritize clarity over cleverness.
- Add minimal docstrings where helpful.
- Use variable names like old_balance or old_total when asserting postconditions for clarity.
- No third-party libraries. Only rely on the Python standard library (Decimal optional).
- Maintain deterministic behavior—no randomness, no time-based logic.

Example Outline (non-binding)
- class BankAccount:
  - __init__(owner: str, balance: int = 0, account_id: str | None = None)
  - deposit(self, amount: int) -> None
  - withdraw(self, amount: int) -> None
  - get_balance(self) -> int
  - _check_invariants(self) -> None
- def transfer(from_acct: BankAccount, to_acct: BankAccount, amount: int) -> None

Acceptance Guidance
- Public API uses exceptions for invalid inputs (deposit, withdraw, transfer).
- At least three assertions with descriptive messages exist.
- There is a _check_invariants method and it is called after each mutation.
- There is a debug-only check guarded by if __debug__:.
- Postcondition checks reference old_balance (or similar) variables.
- Transfer includes an assertion confirming conservation of total funds.
- No catching AssertionError; no assert used for security or input validation; no side effects in assert expressions.

Non-Goals
- Concurrency, persistence, or multi-currency support.
- Complex account types or overdraft/credit features.
- External configuration or environment dependencies.

Output Path Conventions
- Do not alter the paths; write exactly to the specified output/ locations:
  - output/src/bank.py
  - output/tests/smoke.py
  - output/README.md