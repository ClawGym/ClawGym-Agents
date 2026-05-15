"""
Discount and fee rules for the academy.

- TEAM10: 10% off Control category items only.
- POWER20: 20% off Power category items only.
- NEWCLIENT5: $5 off transactions with quantity == 1 (any category).
- BUNDLE5: $5 off per unit when quantity >= 3 (any category).

One discount code per transaction. If a discount_code doesn't match a rule, apply no discount.
Payment processing fee: if payment_method == 'card', fee is 2.5% of (gross - discount); if 'cash', fee is 0.
No tax applied.
"""

TAX_RATE = 0.0  # No tax in current analysis
PROCESSING_FEE_RATE_CARD = 0.025

# Recognized discount codes
VALID_CODES = {"TEAM10", "POWER20", "NEWCLIENT5", "BUNDLE5"}


def discount_amount(category: str, unit_price: float, quantity: int, discount_code: str) -> float:
    """Return the absolute discount amount for a transaction based on code, category, and quantity.
    Rounds to 2 decimals where needed to reflect currency precision.
    """
    gross = unit_price * quantity
    if discount_code == "TEAM10" and category == "Control":
        return round(gross * 0.10, 2)
    elif discount_code == "POWER20" and category == "Power":
        return round(gross * 0.20, 2)
    elif discount_code == "NEWCLIENT5" and quantity == 1:
        return 5.00
    elif discount_code == "BUNDLE5" and quantity >= 3:
        return round(5.00 * quantity, 2)
    else:
        return 0.0


def processing_fee(post_discount_amount: float, payment_method: str) -> float:
    """Return the processing fee based on payment_method.
    Card payments incur a 2.5% fee on the post-discount amount; cash has no fee.
    """
    if payment_method == "card":
        return round(post_discount_amount * PROCESSING_FEE_RATE_CARD, 2)
    return 0.0
