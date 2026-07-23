"""
PII encryption at rest.

Resume text, contact emails, phone numbers, and outreach recipients are
personal data. We encrypt them at rest with Fernet (AES-128-CBC + HMAC) and
key the cipher from the ``CAREERAGENT_ENCRYPTION_KEY`` environment variable.

Two primitives are exposed:

* ``EncryptedString`` -- a SQLAlchemy ``TypeDecorator`` that transparently
  encrypts on write and decrypts on read. Use it for *display* PII that we
  never need to filter on (Fernet output is non-deterministic, so encrypted
  columns cannot be used in ``WHERE col = ...``).
* ``deterministic_hash`` -- an HMAC-SHA256 hex digest for values we must match
  on (e.g. suppression-list lookups, dedup keys). Deterministic, one-way.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy import String, TypeDecorator

ENV_KEY = "CAREERAGENT_ENCRYPTION_KEY"


@lru_cache(maxsize=1)
def _get_cipher() -> Fernet:
    """Return a process-wide Fernet cipher.

    Reads the key from ``CAREERAGENT_ENCRYPTION_KEY``. If unset, a key is
    generated for the lifetime of the process and a warning is emitted -- this
    keeps local/dev runs working, but data written under an ephemeral key
    cannot be decrypted in a later process. Production and tests should set the
    env var explicitly.
    """
    key = os.environ.get(ENV_KEY)
    if not key:
        key = Fernet.generate_key().decode()
        os.environ[ENV_KEY] = key
        import warnings

        warnings.warn(
            f"{ENV_KEY} not set; generated an ephemeral key. Data encrypted "
            "now will not be readable in a future process. Set the env var to "
            "persist PII across runs.",
            RuntimeWarning,
            stacklevel=2,
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: Optional[str]) -> Optional[str]:
    """Encrypt a string, returning URL-safe base64 ciphertext (or None)."""
    if value is None:
        return None
    return _get_cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: Optional[str]) -> Optional[str]:
    """Decrypt ciphertext produced by :func:`encrypt` (or None)."""
    if token is None:
        return None
    return _get_cipher().decrypt(token.encode("ascii")).decode("utf-8")


def deterministic_hash(value: str) -> str:
    """HMAC-SHA256 hex digest keyed by the encryption secret.

    Deterministic and one-way: safe for equality lookups (suppression list,
    dedup) without exposing the plaintext.
    """
    key = os.environ.get(ENV_KEY) or _get_cipher()  # ensure a key exists
    if isinstance(key, Fernet):  # _get_cipher() side-effected the env var
        key = os.environ[ENV_KEY]
    normalized = value.strip().lower().encode("utf-8")
    return hmac.new(key.encode("utf-8"), normalized, hashlib.sha256).hexdigest()


class EncryptedString(TypeDecorator):
    """A String column whose value is encrypted at rest with Fernet."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        return encrypt(value)

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        return decrypt(value)
