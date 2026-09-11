"""Password hashing and verification.

This is a *simulation* of shadow-password hashing. It uses a random salt and
SHA-256 in a crypt-like ``$5$salt$digest`` format. It is intentionally simple
and is NOT meant to be a real cryptographic password store.

Special stored values, as in real /etc/shadow:
    ""    -> no password (login without a password)
    "!"   -> account locked (password login disabled)
    "*"   -> no valid password (login disabled)
"""

from __future__ import annotations

import hashlib
import secrets
import string

_SALT_ALPHABET = string.ascii_letters + string.digits


def make_salt(length=8):
    return "".join(secrets.choice(_SALT_ALPHABET) for _ in range(length))


def hash_password(password, salt=None):
    if salt is None:
        salt = make_salt()
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"$5${salt}${digest}"


def verify_password(password, stored):
    if stored in ("!", "*", "!!"):
        return False          # locked / disabled
    if stored == "":
        return password == ""  # passwordless account
    if not stored.startswith("$5$"):
        return False
    try:
        _, _, salt, _digest = stored.split("$", 3)
    except ValueError:
        return False
    return hash_password(password, salt) == stored


def is_locked(stored):
    return stored in ("!", "*", "!!")
