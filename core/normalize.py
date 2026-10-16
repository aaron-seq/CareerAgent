"""
Normalization helpers shared across ingestion, dedup, and tracking.

A *dedup key* is a stable, lowercased fingerprint of (title, company,
location) used to collapse the same role seen on multiple boards and to
prevent duplicate applications.

Timestamps follow one convention repo-wide: **timezone-aware datetimes in
UTC** (ADR 0008). :func:`utc_now` is the single producer of "now" and
:func:`ensure_utc` is the boundary coercion for datetimes arriving from
anywhere else -- ``dateutil``-parsed board dates (aware only when the source
string carries an offset), caller-supplied ``now``/``as_of`` arguments, and
rows reloaded from a store that kept no offset. A naive value is taken to
already hold UTC; an aware one is converted, never merely relabelled.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
# Common company suffixes that add noise to matching.
_COMPANY_SUFFIXES = {
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "corp",
    "corporation",
    "co",
    "gmbh",
    "plc",
    "sa",
    "ag",
    "bv",
    "the",
}


def utc_now() -> datetime:
    """Current time as an aware UTC datetime.

    The replacement for ``datetime.utcnow()``, which is deprecated and returns
    a naive value. The storage layer (``core.db.tables.UTCDateTime``) persists
    and returns aware UTC, so values from here compare cleanly with rows read
    back from the database.
    """
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Coerce a datetime to the aware-UTC convention.

    Naive values are assumed to hold UTC already and get ``tzinfo=UTC``
    attached (no shift). Aware values are *converted* to UTC, so midnight
    +05:30 becomes 18:30 UTC the previous day rather than midnight UTC.
    Idempotent, and safe to call on either side of every comparison or
    subtraction -- mixing naive and aware values raises ``TypeError``.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clean(text: str) -> str:
    text = _NON_ALNUM.sub(" ", text.lower())
    return _WS.sub(" ", text).strip()


def normalize_company_name(name: str) -> str:
    """Lowercase, strip punctuation and common corporate suffixes."""
    cleaned = _clean(name or "")
    tokens = [t for t in cleaned.split(" ") if t and t not in _COMPANY_SUFFIXES]
    return " ".join(tokens)


def normalize_title(title: str) -> str:
    """Lowercase job title with punctuation collapsed."""
    return _clean(title or "")


def normalize_location(location: str | None) -> str:
    """Normalize a location, treating remote variants as ``remote``."""
    if not location:
        return ""
    cleaned = _clean(location)
    if "remote" in cleaned or "anywhere" in cleaned:
        return "remote"
    # Keep only the first locality token group (city) to be forgiving of
    # "San Francisco, CA, USA" vs "San Francisco".
    first = cleaned.split(" ")
    return " ".join(first[:2]) if first else cleaned


def compute_dedup_key(title: str, company: str, location: str | None = None) -> str:
    """Stable fingerprint used to collapse duplicate postings."""
    return "|".join(
        [
            normalize_title(title),
            normalize_company_name(company),
            normalize_location(location),
        ]
    )
