"""Password hashing with scrypt from the standard library.

Each password gets its own random salt; the stored form names its parameters
so they can be raised later without invalidating existing passwords.
"""

import base64
import hashlib
import hmac
import secrets

MIN_LENGTH = 8
MAX_LENGTH = 128
_N, _R, _P, _SIZE = 2**15, 8, 1, 32
_MAXMEM = 64 * 1024 * 1024


class WeakPasswordError(ValueError):
    """The password does not meet the length rules."""


def check_password(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPasswordError(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise WeakPasswordError(f"Use at most {MAX_LENGTH} characters.")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=_MAXMEM, dklen=_SIZE
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, _N, _R, _P)
    encode = base64.urlsafe_b64encode
    return f"scrypt${_N}${_R}${_P}${encode(salt).decode()}${encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.urlsafe_b64decode(digest)
        actual = _derive(password, base64.urlsafe_b64decode(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Checked when no account matches, so an unknown email costs the same time.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
