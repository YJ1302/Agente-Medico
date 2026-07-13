"""Security primitives: password hashing and verification.

Uses passlib with bcrypt. Plain-text passwords are never stored; only salted
bcrypt hashes are persisted (see SECURITY_AND_PRIVACY_RULES.md).
"""

from __future__ import annotations

from passlib.context import CryptContext

# bcrypt has a 72-byte input limit; passlib handles truncation warnings.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Return a salted bcrypt hash for the given plain-text password."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if the plain password matches the stored hash."""
    try:
        return _pwd_context.verify(plain_password, hashed_password)
    except ValueError:
        # Malformed hash — treat as a failed verification rather than crashing.
        return False
