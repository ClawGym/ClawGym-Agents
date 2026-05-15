from __future__ import annotations


class User:
    def __init__(self, name: str, age: int) -> None:
        self.name = name
        self.age = age

    def is_adult(self) -> bool:
        """Return True if the user is considered an adult.

        This method applies a simple age-based check.

        Returns:
            bool: True if age >= 18, otherwise False.
        """
        return self.age >= 18