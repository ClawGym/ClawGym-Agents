import re
from typing import Dict, Any


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(email: str) -> bool:
    """
    Simple email validator: returns True for basic 'name@domain.tld' patterns.
    """
    return bool(EMAIL_RE.match(email))


class UserService:
    """
    A small async user service that validates email and inserts users via an async DB client.
    The DB client is expected to expose an async method: insert(data: dict) -> dict
    """
    def __init__(self, db):
        self._db = db

    def _validate_email(self, email: str) -> bool:
        return validate_email(email)

    async def create_user(self, name: str, email: str) -> Dict[str, Any]:
        """
        Validate input and persist via the async DB client.
        Returns the inserted record dict from the DB client.
        """
        if not self._validate_email(email):
            raise ValueError("Invalid email")
        result = await self._db.insert({"name": name, "email": email})
        return result