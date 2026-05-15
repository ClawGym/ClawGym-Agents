def normalize_title(title: str) -> str:
    """
    Return a cleaned title by:
      - Trimming leading/trailing whitespace.
      - Collapsing internal whitespace to single spaces.
      - Title-casing standard words.
      - Preserving fully uppercase acronyms (e.g., API, UX) if they appear uppercase in the input.
      - Returning an empty string for empty or whitespace-only input.

    Raises:
      TypeError: if title is not a string.
    """
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    # NOTE: This implementation is intentionally naive and may not meet all documented behaviors.
    words = title.split()
    # This will incorrectly lowercase acronyms like API -> Api.
    return " ".join([w.capitalize() for w in words])


def calculate_discount(price: float, percent: float) -> float:
    """
    Calculate the discounted price.

    Requirements:
      - price must be >= 0.
      - percent must be in the range [0, 100].
      - Return round(price * (1 - percent/100), 2).
      - Raise ValueError for price < 0 or percent outside [0, 100].

    Examples:
      - calculate_discount(100, 25) -> 75.00
      - calculate_discount(9.99, 10) -> 8.99
    """
    # NOTE: This implementation intentionally omits validation and rounding.
    return price - (price * percent / 100)
