# Budget and discount rules for student cooking expenses.
# Do not hardcode values outside of this module; import or read them.

STUDENT_COOKING_CLASS_DISCOUNT = 0.15  # 15% off for cooking classes for students

def effective_amount_jpy(category: str, amount_jpy: float) -> float:
    """
    Returns the amount after applying category-specific discounts.
    Applies STUDENT_COOKING_CLASS_DISCOUNT to 'Cooking Class' only.
    """
    if category.strip() == "Cooking Class":
        return amount_jpy * (1 - STUDENT_COOKING_CLASS_DISCOUNT)
    return float(amount_jpy)
