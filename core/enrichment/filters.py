"""
Job filters: predicates and helpers to narrow a set of postings.

Operate on domain :class:`~core.models.JobPosting` objects (or anything with
``title``/``description``/``remote``) so they're reusable in the UI, digests,
and the pipeline.
"""

from __future__ import annotations

import re

_NEW_GRAD = re.compile(
    r"\b(new ?grad|graduate|entry[- ]level|junior|early career)\b", re.I
)
_INTERN = re.compile(r"\b(intern|internship|co[- ]?op)\b", re.I)
_SENIOR = re.compile(r"\b(senior|staff|principal|lead|manager|director)\b", re.I)


def is_new_grad(title: str, description: str = "") -> bool:
    """New-grad/entry-level, and not simultaneously a senior role."""
    text = f"{title} {description}"
    if _SENIOR.search(title):
        return False
    return bool(_NEW_GRAD.search(text))


def is_internship(title: str, description: str = "") -> bool:
    return bool(_INTERN.search(f"{title} {description}"))


def filter_by_min_score(jobs, threshold: float):
    """Keep jobs with a match_score >= threshold (rows expose match_score)."""
    return [j for j in jobs if (getattr(j, "match_score", None) or 0) >= threshold]


def filter_remote(jobs):
    return [j for j in jobs if getattr(j, "remote", False)]


def exclude_ghosts(jobs, max_ghost_score: float = 0.6):
    return [
        j for j in jobs if (getattr(j, "ghost_score", None) or 0) <= max_ghost_score
    ]
