"""
Salary parsing and enrichment.

Turns free-text salary strings ("$180K - $220K", "£60,000", "80k-100k USD")
into structured (min, max, currency), and backfills ``salary_min/max`` on job
rows that only have a ``salary_range`` string.
"""

from __future__ import annotations

import re
from typing import Optional

_CURRENCY = {"$": "USD", "£": "GBP", "€": "EUR"}
_CODE_RE = re.compile(r"\b(USD|GBP|EUR|CAD|AUD)\b", re.I)
_NUM_RE = re.compile(r"(\d[\d,]*\.?\d*)\s*([kK])?")


def _to_number(num: str, suffix: str | None) -> float:
    value = float(num.replace(",", ""))
    if suffix and suffix.lower() == "k":
        value *= 1000
    return value


def parse_salary(
    text: str,
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Parse a salary string into (min, max, currency). Any part may be None."""
    if not text:
        return None, None, None

    currency: Optional[str] = None
    for symbol, code in _CURRENCY.items():
        if symbol in text:
            currency = code
            break
    if currency is None:
        m = _CODE_RE.search(text)
        if m:
            currency = m.group(1).upper()

    numbers = [_to_number(n, s) for n, s in _NUM_RE.findall(text)]
    # Ignore bare years-ish small numbers only if clearly not salary? Keep simple.
    if not numbers:
        return None, None, currency
    if len(numbers) == 1:
        return numbers[0], numbers[0], currency
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1]), currency


class SalaryEnricher:
    """Backfill structured salary on rows that only have a text range."""

    def enrich(self, session) -> int:
        from ..db.repository import JobRepository

        repo = JobRepository(session)
        updated = 0
        for row in repo.list(include_duplicates=True):
            if row.salary_min is not None:
                continue
            text = (row.extra or {}).get("salary_range")
            if not text:
                continue
            smin, smax, currency = parse_salary(text)
            if smin is not None:
                row.salary_min = smin
                row.salary_max = smax
                row.salary_currency = row.salary_currency or currency
                session.add(row)
                updated += 1
        session.flush()
        return updated
