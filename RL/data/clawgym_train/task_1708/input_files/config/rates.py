ACTBLUE_PERCENT = 0.039
ACTBLUE_FIXED = 0.30
WINRED_PERCENT = 0.039
WINRED_FIXED = 0.30

def expected_fee(amount: float, source: str) -> float:
    """
    Compute the expected payment processor fee for a transaction.

    Rules:
    - For ActBlue: fee = amount * ACTBLUE_PERCENT + ACTBLUE_FIXED
    - For WinRed: fee = amount * WINRED_PERCENT + WINRED_FIXED
    - Refunds are represented as negative amounts and should produce negative fees of the same magnitude as if computed on the absolute amount (apply the sign of amount at the end).
    - Round to the nearest cent (two decimals) after computing percent+fixed.
    """
    rate_percent = ACTBLUE_PERCENT if source == "ActBlue" else WINRED_PERCENT
    fixed = ACTBLUE_FIXED if source == "ActBlue" else WINRED_FIXED
    sign = -1 if amount < 0 else 1
    base = abs(amount) * rate_percent + fixed
    return sign * round(base, 2)
