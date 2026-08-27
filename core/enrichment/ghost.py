"""
Ghost-job detection heuristic.

"Ghost jobs" are postings that stay open without real intent to hire. Signals:
a stale ``datePosted``, frequent reposting, and a vague/short description. We
combine them into a 0-1 score (higher = more likely a ghost) plus reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..normalize import to_naive_utc, utc_now


@dataclass
class GhostAssessment:
    score: float
    reasons: list[str] = field(default_factory=list)


def _age_days(date_posted: datetime | None, now: datetime) -> float | None:
    if date_posted is None:
        return None
    # Either side may arrive aware: ``date_posted`` comes from the boards via
    # ``dateutil``, which keeps an offset when the source string has one, while
    # rows reloaded from the DB are always naive. Both land on naive UTC before
    # any arithmetic, so this never raises on a mixed pair.
    return (to_naive_utc(now) - to_naive_utc(date_posted)).total_seconds() / 86400.0


def ghost_score(
    date_posted: datetime | None,
    now: datetime | None = None,
    repost_count: int = 0,
    description: str = "",
) -> GhostAssessment:
    now = now or utc_now()
    score = 0.0
    reasons: list[str] = []

    age = _age_days(date_posted, now)
    if age is not None:
        if age > 90:
            score += 0.5
            reasons.append(f"open {int(age)} days (>90)")
        elif age > 45:
            score += 0.3
            reasons.append(f"open {int(age)} days (>45)")

    if repost_count >= 3:
        score += 0.3
        reasons.append(f"reposted {repost_count} times")
    elif repost_count == 2:
        score += 0.15
        reasons.append("reposted twice")

    if description is not None and len(description.strip()) < 200:
        score += 0.2
        reasons.append("very short/vague description")

    return GhostAssessment(score=min(score, 1.0), reasons=reasons)


class GhostAnnotator:
    """Store a ghost score on each job row."""

    def annotate(self, session, now: datetime | None = None) -> int:
        from ..db.repository import JobRepository

        repo = JobRepository(session)
        updated = 0
        for row in repo.list(include_duplicates=True):
            assessment = ghost_score(
                row.date_posted, now=now, description=row.description or ""
            )
            row.ghost_score = assessment.score
            session.add(row)
            updated += 1
        session.flush()
        return updated
