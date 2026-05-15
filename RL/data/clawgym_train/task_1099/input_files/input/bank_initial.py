"""
Flawed banking module — to be refactored using defensive programming and design-by-contract.

Notes:
- Uses floats for money (bad idea).
- Uses assertions for user input validation (anti-pattern).
- Side effects in assert expressions (anti-pattern).
- Catches AssertionError to change control flow (anti-pattern).
- Security checks expressed via assert (anti-pattern).
"""

from typing import List, Tuple, Optional

TRANSACTION_FEE = 0.50  # arbitrary fee (not documented), deducted on withdraw and transfer


class DummyUser:
    """Pretend user object for 'security' checks (bad idea to assert on this)."""
    def __init__(self, is_admin: bool = False):
        self._is_admin = is_admin

    def is_admin(self) -> bool:
        return self._is_admin


class BankAccount:
    def __init__(self, owner: str, balance: float = 0.0, account_id: Optional[str] = None):
        # Using asserts for input validation (anti-pattern)
        assert owner, "owner must not be empty"
        assert balance >= 0
        self.owner = owner
        self.balance = float(balance)
        self.account_id = account_id or f"acct-{id(self)}"
        self.transactions: List[Tuple[str, float, float]] = []  # (type, amount, resulting_balance)
        # No invariant checks here

    def get_balance(self) -> float:
        return self.balance

    def deposit(self, amount: float) -> None:
        # Using assertions for public input validation (anti-pattern)
        assert amount > 0, "amount must be positive"
        # Side-effect in assert expression (anti-pattern): appending to log inside assert
        assert self._audit_log(f"DEPOSIT request: {amount}") is True
        old = self.balance
        self.balance += float(amount)
        # log deposit (side-effect in assert again)
        assert self._record("deposit", float(amount))  # returns True, but still a side-effect in assert
        # weak/no postcondition message
        assert self.balance == old + amount

    def withdraw(self, amount: float) -> None:
        # Try to "recover" by catching AssertionError (anti-pattern)
        try:
            assert amount > 0, "amount must be positive"
        except AssertionError:
            # silently coerce to minimum
            amount = 0.01
        # Using assert for insufficient funds (anti-pattern)
        assert self.balance >= amount + TRANSACTION_FEE, "insufficient funds"
        old = self.balance
        self.balance -= float(amount + TRANSACTION_FEE)
        # side-effect in assert
        assert self._record("withdraw", float(amount))
        # weak postcondition and hidden fee
        assert self.balance == old - (amount + TRANSACTION_FEE)

    def _record(self, kind: str, amount: float) -> bool:
        # internal helper with side effects; returns True for use in assert (anti-pattern)
        self.transactions.append((kind, float(amount), float(self.balance)))
        return True

    def _audit_log(self, message: str) -> bool:
        # pretend to write to some log; return True
        # (Using in assert is still a side-effect in an assert expression)
        # In reality, this would write to disk or external system.
        _ = message  # suppress unused
        return True


def transfer(from_acct: BankAccount, to_acct: BankAccount, amount: float,
             user: Optional[DummyUser] = None, token: Optional[str] = None) -> None:
    """
    Flawed transfer:
    - Uses assert for authorization and token validity (anti-pattern).
    - Uses assert for input validation (anti-pattern).
    - Applies hidden fee removing money from the system (breaks conservation).
    """
    # Security and token checks in asserts (anti-patterns)
    assert user is not None and user.is_admin(), "unauthorized transfer"
    assert token and len(token) > 10, "token invalid"

    # Input validation with assert (anti-pattern)
    assert amount > 0, "amount must be positive"
    assert isinstance(from_acct, BankAccount) and isinstance(to_acct, BankAccount), "invalid accounts"
    assert from_acct is not to_acct, "cannot transfer to same account"
    assert from_acct.get_balance() >= amount + TRANSACTION_FEE, "insufficient funds"

    # Perform transfer with a hidden fee that is simply destroyed (breaks conservation)
    # Side-effect in assert: try to "log" the transfer
    assert from_acct._audit_log(f"TRANSFER start {amount} from {from_acct.account_id} to {to_acct.account_id}") is True

    before_total = from_acct.get_balance() + to_acct.get_balance()

    # mutate state
    old_from = from_acct.balance
    old_to = to_acct.balance

    from_acct.balance -= float(amount + TRANSACTION_FEE)
    to_acct.balance += float(amount)

    # Side-effect in assert: record both sides
    assert from_acct._record("transfer_out", float(amount))
    assert to_acct._record("transfer_in", float(amount))

    after_total = from_acct.get_balance() + to_acct.get_balance()

    # Postcondition is not checking conservation correctly due to fee
    # and lacks a descriptive message
    assert after_total <= before_total  # wrong direction, imprecise


# Naive demo usage (not tests)
if __name__ == "__main__":
    a = BankAccount("Alice", 100.0)
    b = BankAccount("Bob", 5.0)
    admin = DummyUser(is_admin=True)
    transfer(a, b, 10.0, user=admin, token="verylongtokendata")
    print(a.get_balance(), b.get_balance())