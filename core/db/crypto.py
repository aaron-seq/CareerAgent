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
import json
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy import String, TypeDecorator

ENV_KEY = "CAREERAGENT_ENCRYPTION_KEY"


@lru_cache(maxsize=1)
def _get_key() -> bytes:
    """Use the configured key, or atomically retain a private local dev key.

    Publishing a complete temporary file with link() avoids another process
    reading a partially written key. Never replace an existing key: both
    encrypted records and suppression hashes depend on it across restarts.
    """
    key = os.environ.get(ENV_KEY)
    if key:
        value = key.encode()
    else:
        path = Path(os.environ.get("CAREERAGENT_KEY_PATH") or ".careeragent_key")
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".careeragent-key-", delete=False
            ) as file:
                temporary = Path(file.name)
                file.write(Fernet.generate_key())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass  # another process published its complete key first
            finally:
                temporary.unlink()
        value = path.read_bytes().strip()
    Fernet(value)  # reject invalid supplied/stored keys before any write
    return value


def _get_cipher() -> Fernet:
    return Fernet(_get_key())


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
    normalized = value.strip().lower().encode("utf-8")
    return hmac.new(_get_key(), normalized, hashlib.sha256).hexdigest()


def encrypt_payload(value: dict) -> dict:
    """Encrypt a JSON artifact without storing candidate fields in plaintext."""
    return {
        "format": "careeragent.fernet.v1",
        "ciphertext": encrypt(json.dumps(value, default=str)),
    }


def decrypt_payload(value: dict) -> dict:
    """Read encrypted artifacts and existing plaintext legacy JSON."""
    if value.get("format") == "careeragent.fernet.v1":
        plaintext = decrypt(value["ciphertext"])
        if plaintext is None:
            raise ValueError("Encrypted payload has no ciphertext.")
        return json.loads(plaintext)
    return value


class EncryptedString(TypeDecorator):
    """A String column whose value is encrypted at rest with Fernet."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        return encrypt(value)

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        return decrypt(value)
