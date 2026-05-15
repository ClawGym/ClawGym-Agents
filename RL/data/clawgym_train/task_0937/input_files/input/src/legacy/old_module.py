"""Legacy utilities.

This module is part of a legacy subsystem. The existing Google Style docstrings
must remain unchanged by any automated tooling.
"""


def legacy_sum(x: int, y: int) -> int:
    """Add two integers in a legacy-safe manner.

    Args:
        x (int): The first integer.
        y (int): The second integer.

    Returns:
        int: The sum of x and y.

    Raises:
        TypeError: If either argument is not an integer.
    """
    if not isinstance(x, int) or not isinstance(y, int):
        raise TypeError("Both x and y must be integers.")
    return x + y


class LegacyProcessor:
    """Process records using a stable, backward-compatible workflow.

    This class exists to support old integrations without breaking changes.
    """

    def __init__(self, multiplier: int = 1) -> None:
        """Initialize the processor.

        Args:
            multiplier (int, optional): A scaling factor applied during processing.
                Defaults to 1.

        Raises:
            ValueError: If multiplier is less than 1.
        """
        if multiplier < 1:
            raise ValueError("multiplier must be >= 1.")
        self._multiplier = multiplier

    def process(self, items):
        """Process a sequence of numeric items.

        Applies the configured multiplier to each item.

        Args:
            items (Iterable[Number]): The input items to process.

        Returns:
            list: A list containing the processed items, in order.

        Raises:
            ValueError: If any item is not a number.
        """
        result = []
        for it in items:
            if not isinstance(it, (int, float)):
                raise ValueError("All items must be numeric.")
            result.append(it * self._multiplier)
        return result