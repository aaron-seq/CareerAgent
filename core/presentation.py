"""
Pure presentation helpers for the UI layer.

Wording and formatting decisions live here rather than in ``app.py`` so they
can be unit-tested: how a match score is worded, when a salary is worth
showing, which risks to surface on a job card. No Streamlit imports and no
side effects -- every function is a function of its arguments, and each takes
the plain job dicts that ``core.facade.top_jobs`` returns.

Enrichment fields are tri-state (``None`` = unknown): only an explicit
``True`` produces a chip or a warning, so missing data never reads as a fact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Tuple, Union

from .normalize import ensure_utc, utc_now

#: Ghost-risk score above which a posting is flagged (matches the Pipeline
#: "Hide likely ghost jobs" filter).
GHOST_RISK_THRESHOLD = 0.6

_CURRENCY_SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€"}


def format_salary(
    minimum: Optional[float],
    maximum: Optional[float] = None,
    currency: Optional[str] = None,
) -> Optional[str]:
    """``"$120k–150k"``, or ``None`` when there is nothing worth showing."""
    if not minimum and not maximum:
        return None
    code = (currency or "").upper()
    prefix = _CURRENCY_SYMBOLS.get(code) or (f"{code} " if code else "")

    def money(value: float) -> str:
        if value >= 1000 and value % 1000 == 0:
            return f"{int(value // 1000)}k"
        return f"{int(value):,}"

    if minimum and maximum and maximum != minimum:
        return f"{prefix}{money(minimum)}–{money(maximum)}"
    return f"{prefix}{money(minimum or maximum or 0)}"


def format_relative_date(
    value: Union[datetime, str, None], now: Optional[datetime] = None
) -> Optional[str]:
    """``"today"`` / ``"3 days ago"`` / ``"2 months ago"``.

    Accepts a datetime or an ISO string (as facade dicts carry it); naive
    values are treated as UTC and aware ones converted, so both conventions
    compare correctly. Unparseable input gives ``None`` rather than a guess.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    days = (ensure_utc(now or utc_now()) - ensure_utc(value)).days
    if days < 0:
        return "just posted"
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    months = days // 30
    return f"{months} month{'s' if months > 1 else ''} ago"


def match_quality(score: Optional[float]) -> Tuple[str, str]:
    """A word and a tone for a 0-100 match score; a bare '43%' means little."""
    if score is None:
        return "Unscored", "neutral"
    if score >= 75:
        return "Strong match", "good"
    if score >= 55:
        return "Good match", "good"
    if score >= 35:
        return "Fair match", "warn"
    return "Weak match", "bad"


def truncate(text: Optional[str], limit: int = 140) -> str:
    """Trim to a word boundary with an ellipsis."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return f"{cut}…"


def job_chips(job: dict[str, Any], now: Optional[datetime] = None) -> list[str]:
    """The short facts worth showing on a job card, in priority order."""
    chips: list[str] = []
    if job.get("remote"):
        chips.append("Remote")
    if job.get("location"):
        chips.append(str(job["location"]))
    salary = format_salary(
        job.get("salary_min"), job.get("salary_max"), job.get("salary_currency")
    )
    if salary:
        chips.append(salary)
    posted = format_relative_date(job.get("date_posted"), now=now)
    if posted:
        chips.append(f"Posted {posted}")
    if job.get("sponsors_visa") is True:
        chips.append("Visa sponsor")
    return chips


def risk_notes(job: dict[str, Any]) -> list[str]:
    """Warnings worth surfacing before someone spends time applying."""
    notes = []
    ghost = job.get("ghost_score")
    if ghost is not None and ghost > GHOST_RISK_THRESHOLD:
        notes.append(f"Possible ghost job ({ghost:.0%} risk): stale or vague posting.")
    if job.get("had_layoffs") is True:
        notes.append("This employer had recent layoffs.")
    return notes
