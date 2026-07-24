"""
Normalization helpers shared across ingestion, dedup, and tracking.

A *dedup key* is a stable, lowercased fingerprint of (title, company,
location) used to collapse the same role seen on multiple boards and to
prevent duplicate applications.
"""

from __future__ import annotations

import re

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
