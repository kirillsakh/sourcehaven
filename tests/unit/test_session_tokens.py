import hashlib

from sourcehaven.sessions.tokens import hash_token, new_token


def test_tokens_are_unique_and_hash_is_sha256() -> None:
    first: str = new_token()
    assert first != new_token() and len(first) >= 43
    assert hash_token(first) == hashlib.sha256(first.encode()).digest()
