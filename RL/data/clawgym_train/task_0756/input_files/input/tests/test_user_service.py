import pytest
from unittest.mock import Mock, patch

from src.service import UserService, validate_email


# Missing @pytest.mark.asyncio and using Mock for an async call site.
# Also not awaiting the coroutine returned by create_user and not verifying call arguments.
async def test_create_user_inserts_into_db():
    mock_db = Mock()
    mock_db.insert.return_value = {"id": 1, "name": "Alice", "email": "alice@example.com"}

    service = UserService(mock_db)
    result = service.create_user("Alice", "alice@example.com")  # Not awaited (anti-pattern)
    assert result["name"] == "Alice"  # This is operating on a coroutine, not the actual result


# Over-mocking a private helper that should not be patched in tests.
def test_create_user_allows_invalid_email_when_helper_patched():
    with patch.object(UserService, "_validate_email", return_value=True):
        mock_db = Mock()
        mock_db.insert.return_value = {"id": 2, "name": "Bob", "email": "not-an-email"}
        service = UserService(mock_db)
        created = service.create_user("Bob", "not-an-email")  # Not awaited; bypassing real validation
        assert created  # Weak assertion, also on coroutine


# Duplicated tests for email validation instead of using @pytest.mark.parametrize
def test_validate_email_valid():
    assert validate_email("user@example.com") is True

def test_validate_email_valid_subdomain():
    assert validate_email("user@mail.example.com") is True

def test_validate_email_invalid_no_at():
    assert validate_email("userexample.com") is False

def test_validate_email_invalid_no_domain():
    assert validate_email("user@") is False