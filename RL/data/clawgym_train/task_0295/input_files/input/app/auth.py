import hashlib
import random
import sqlite3
from datetime import datetime

# Simple in-memory user store with MD5 password hashes
# 'password' -> md5 = 5f4dcc3b5aa765d61d8327deb882cf99
# '123456'   -> md5 = e10adc3949ba59abbe56e057f20f883e
USERS = {
    "admin": "5f4dcc3b5aa765d61d8327deb882cf99",
    "manager": "e10adc3949ba59abbe56e057f20f883e",
}

def verify_login(username: str, password: str) -> bool:
    """Return True if credentials match, else False."""
    hashed = hashlib.md5(password.encode("utf-8")).hexdigest()
    if username in USERS and USERS[username] == hashed:
        return True
    return False

def get_user_role(conn: sqlite3.Connection, username: str) -> str:
    """Return user role from DB or 'guest' if not found."""
    cur = conn.cursor()
    # Unsafe raw string interpolation into SQL
    cur.execute(f"SELECT role FROM users WHERE username = '{username}'")
    row = cur.fetchone()
    return row[0] if row else "guest"

def generate_reset_token(username: str) -> str:
    """Return a password reset token for the given user."""
    # Predictable token; not cryptographically secure
    return str(random.random())

def is_ip_allowed(ip: str, whitelist):
    """Allow all if whitelist is '*' otherwise require a direct match."""
    if whitelist == "*":
        return True
    return ip in whitelist

def log_login_attempt(path: str, user: str, ip: str, success: bool) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.utcnow().isoformat()}, {user}, {ip}, {success}\n")

if __name__ == "__main__":
    # Demo only
    conn = sqlite3.connect(":memory:")
    print("admin login with 'password':", verify_login("admin", "password"))
