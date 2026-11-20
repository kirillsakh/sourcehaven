import hashlib
import secrets


def new_token() -> str:
    """Return an unguessable session token with 256 bits of randomness."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    """Return the SHA-256 digest under which a token is stored.

    The token is high-entropy, so a fast unsalted hash suffices; only the digest reaches the
    database, so a database leak does not yield usable cookies.
    """
    return hashlib.sha256(token.encode()).digest()
