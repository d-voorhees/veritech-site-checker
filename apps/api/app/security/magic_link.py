import hashlib
import secrets


def generate_magic_link_token() -> str:
    return secrets.token_urlsafe(32)


def hash_magic_link_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
