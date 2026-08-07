"""
Pure presentation helpers for the UI layer.

Formatting and copy decisions live here rather than in ``app.py`` so they can
be unit-tested: how a match score is worded, when a salary range is worth
showing, what an empty screen should tell you to do next. No Streamlit imports,
no side effects -- everything is a function of its arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# The guided flow
# --------------------------------------------------------------------------- #

#: The app's linear journey. Numbered so the sidebar can show progress rather
#: than a flat list of six equal-looking destinations.
STEPS: list[tuple[str, str, str]] = [
    ("onboarding", "Your profile", "Add your CV and the details forms ask for"),
    ("discovery", "Find jobs", "Pull real listings from company and job-board APIs"),
    ("pipeline", "Review & apply", "See your best matches and apply with autofill"),
    ("contacts", "Find contacts", "Optional: reach a human at the company"),
    ("draft", "Write outreach", "Optional: draft a personal email"),
    ("export", "Export", "Digest, resume files, and your data"),
]

#: Steps a first-time user must do; the rest are optional detours.
CORE_STEPS = {"onboarding", "discovery", "pipeline"}


@dataclass
class Step:
    key: str
    label: str
    hint: str
    index: int
    is_core: bool
    done: bool
    current: bool

    @property
    def display(self) -> str:
        """Sidebar label: a tick when done, otherwise its step number."""
        marker = "✓" if self.done else str(self.index)
        suffix = "" if self.is_core else " (optional)"
        return f"{marker}  {self.label}{suffix}"


def build_steps(
    current_page: str,
    has_profile: bool = False,
    has_jobs: bool = False,
    has_applications: bool = False,
) -> list[Step]:
    """Describe each step, marking what's finished and where the user is."""
    done_map = {
        "onboarding": has_profile,
        "discovery": has_jobs,
        "pipeline": has_applications,
    }
    steps = []
    for i, (key, label, hint) in enumerate(STEPS, start=1):
        steps.append(
            Step(
                key=key,
                label=label,
                hint=hint,
                index=i,
                is_core=key in CORE_STEPS,
                done=done_map.get(key, False),
                current=key == current_page,
            )
        )
    return steps


def next_step(steps: list[Step]) -> Optional[Step]:
    """The first unfinished core step -- what to nudge the user toward."""
    for step in steps:
        if step.is_core and not step.done:
            return step
    return None


# --------------------------------------------------------------------------- #
# Empty states
# --------------------------------------------------------------------------- #


@dataclass
class EmptyState:
    headline: str
    body: str
    action_label: Optional[str] = None
    action_page: Optional[str] = None


def empty_state(screen: str, has_profile: bool = False) -> EmptyState:
    """What a blank screen should say.

    An empty screen is the most common moment a user gives up, so each one
    names the single next action rather than just reporting emptiness.
    """
    if screen == "jobs" and not has_profile:
        return EmptyState(
            "Add your profile first",
            "Match scores compare a job against your CV, so there's nothing to "
            "rank until we know about you.",
            "Go to Your profile",
            "onboarding",
        )
    if screen == "jobs":
        return EmptyState(
            "No jobs yet",
            "Pull some in from a company's careers page or a job board — both "
            "work without any API keys.",
            "Find jobs",
            "discovery",
        )
    if screen == "filtered":
        return EmptyState(
            "No jobs match these filters",
            "Your filters are hiding everything you've pulled in. Relax one — "
            "the minimum match score is usually the culprit.",
        )
    if screen == "pipeline":
        return EmptyState(
            "Nothing tracked yet",
            "Add a job to your pipeline from the matches above and it'll show "
            "up here as you move through the stages.",
        )
    if screen == "drafts":
        return EmptyState(
            "No drafts yet",
            "Drafts you write in Write outreach are saved here.",
        )
    return EmptyState("Nothing here yet", "")


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

_CURRENCY_SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€"}


def format_salary(
    minimum: Optional[float],
    maximum: Optional[float] = None,
    currency: Optional[str] = None,
) -> Optional[str]:
    """Human salary range, or ``None`` when there's nothing worth showing."""
    if not minimum and not maximum:
        return None
    symbol = _CURRENCY_SYMBOLS.get((currency or "").upper(), "")
    prefix = symbol or (f"{currency} " if currency else "")

    def money(value: float) -> str:
        if value >= 1000 and value % 1000 == 0:
            return f"{int(value // 1000)}k"
        return f"{int(value):,}"

    if minimum and maximum and maximum != minimum:
        return f"{prefix}{money(minimum)}–{money(maximum)}"
    return f"{prefix}{money(minimum or maximum)}"


def format_relative_date(
    value: Optional[datetime], now: Optional[datetime] = None
) -> Optional[str]:
    """'today' / '3 days ago' / '2 months ago'. Freshness drives urgency."""
    if value is None:
        return None
    now = now or datetime.utcnow()
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    days = (now - value).days
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


def match_quality(score: Optional[float]) -> tuple[str, str]:
    """Turn a raw score into a word and a tone.

    A bare '43%' means little; 'Fair match' tells the user whether to bother.
    """
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
    cut = text[:limit].rsplit(" ", 1)[0]
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
    if job.get("sponsors_visa"):
        chips.append("Visa sponsor")
    return chips


def risk_notes(job: dict[str, Any]) -> list[str]:
    """Warnings worth surfacing before someone spends time applying."""
    notes = []
    ghost = job.get("ghost_score")
    if ghost is not None and ghost > 0.6:
        notes.append(f"Possible ghost job ({ghost:.0%} risk) — stale or vague posting.")
    if job.get("had_layoffs"):
        notes.append("This employer had recent layoffs.")
    return notes
